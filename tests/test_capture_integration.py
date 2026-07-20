"""End-to-end capture against a mock Kalshi WS server.

Exercises the full path: discovery -> startup REST snapshot -> subscribe ->
WS snapshot/deltas/trades journaled -> sequence gap -> gap event journaled ->
REST resync + forced reconnect -> fresh subscription. The wire format here
encodes Doc 1 §1.1's researched message shapes ([VERIFY on first live demo
run] — see docs/12-build-log.md).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

from thorp.common.clock import CaptureClock
from thorp.recorder.capture import KalshiCapture
from thorp.recorder.config import RecorderConfig
from thorp.recorder.journal import JournalSet
from thorp.recorder.kalshi.rest import KalshiRestClient

MARKET = "KXMLBGAME-TEST-A"


class FakeRest(KalshiRestClient):
    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:9")  # never contacted
        self.orderbook_calls: list[str] = []

    async def get_open_markets(self, series_ticker: str) -> list[dict[str, Any]]:
        return [{"ticker": MARKET}]

    async def get_orderbook(self, market_ticker: str) -> dict[str, Any]:
        self.orderbook_calls.append(market_ticker)
        return {"orderbook": {"yes": [[40, 100]], "no": [[55, 50]]}}


def read_stream(root: Path, data_type: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((root / "kalshi" / data_type).rglob("*.jsonl")):
        records.extend(json.loads(line) for line in path.read_text().splitlines())
    return records


async def test_capture_journals_and_recovers_from_gap(tmp_path: Path) -> None:
    connections = 0
    second_snapshot_sent = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        conn = connections
        sub = json.loads(await ws.recv())
        assert sub["cmd"] == "subscribe"
        assert sub["params"]["channels"] == ["orderbook_delta", "trade"]
        assert sub["params"]["market_tickers"] == [MARKET]
        book_sid, trade_sid = conn * 10 + 1, conn * 10 + 2
        for channel, sid in (("orderbook_delta", book_sid), ("trade", trade_sid)):
            ack = {"id": sub["id"], "type": "subscribed", "msg": {"channel": channel, "sid": sid}}
            await ws.send(json.dumps(ack))
        snapshot = {
            "type": "orderbook_snapshot",
            "sid": book_sid,
            "seq": 1,
            "msg": {"market_ticker": MARKET, "yes": [[40, 100]], "no": [[55, 50]]},
        }
        await ws.send(json.dumps(snapshot))
        if conn == 1:
            delta = {"market_ticker": MARKET, "price": 40, "delta": -25, "side": "yes"}
            d2 = {"type": "orderbook_delta", "sid": book_sid, "seq": 2, "msg": delta}
            await ws.send(json.dumps(d2))
            trade = {
                "market_ticker": MARKET,
                "yes_price": 41,
                "no_price": 59,
                "count": 7,
                "taker_side": "no",
                "ts": 1_789_000_000,
            }
            await ws.send(json.dumps({"type": "trade", "sid": trade_sid, "msg": trade}))
            # seq 3 never sent: the client must detect the gap and resync.
            d4 = {"type": "orderbook_delta", "sid": book_sid, "seq": 4, "msg": delta}
            await ws.send(json.dumps(d4))
        else:
            second_snapshot_sent.set()
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        cfg = RecorderConfig(
            data_dir=tmp_path,
            environment="test",
            series_tickers=("KXMLBGAME",),
            rest_url="http://127.0.0.1:9",
            ws_url=f"ws://127.0.0.1:{port}/trade-api/ws/v2",
            snapshot_interval_s=3600,
            discovery_interval_s=3600,
            fsync_interval_s=0.0,
        )
        clock = CaptureClock()
        journals = JournalSet(tmp_path, clock, fsync_interval_s=0.0)
        rest = FakeRest()
        capture = KalshiCapture(cfg, clock, journals, rest, signer=None)

        run_task = asyncio.create_task(capture.run())
        try:
            await asyncio.wait_for(second_snapshot_sent.wait(), timeout=15)
        finally:
            capture.stop()
            await asyncio.wait_for(run_task, timeout=5)
            journals.close()
            await rest.aclose()

    assert connections == 2, "gap must force a reconnect with a fresh subscription"

    deltas = read_stream(tmp_path, "book_deltas")
    assert [d["seq"] for d in deltas] == [2, 4]
    assert deltas[0]["side"] == "bid" and deltas[0]["price"] == "0.4" and deltas[0]["size"] == -25

    gaps = read_stream(tmp_path, "gap_events")
    assert len(gaps) == 1
    assert gaps[0]["expected_seq"] == 3 and gaps[0]["received_seq"] == 4
    assert gaps[0]["gap_size"] == 1
    assert gaps[0]["channel"] == "orderbook_delta"

    trades = read_stream(tmp_path, "trades")
    assert len(trades) == 1
    assert trades[0]["taker_side"] == "sell" and trades[0]["price"] == "0.41"
    assert trades[0]["size"] == 7

    snapshots = read_stream(tmp_path, "book_snapshots")
    ws_snaps = [s for s in snapshots if s["source"] == "ws"]
    rest_snaps = [s for s in snapshots if s["source"] == "rest"]
    assert len(ws_snaps) == 2, "one WS snapshot per subscription"
    assert len(rest_snaps) >= 2, "startup snapshot plus gap-triggered resync snapshot"
    assert ws_snaps[0]["bids"] == [["0.4", 100]] and ws_snaps[0]["asks"] == [["0.45", 50]]
    # REST snapshots after WS traffic are anchored to the last-seen WS seq.
    assert rest_snaps[-1]["seq"] == 4


class MutableRest(FakeRest):
    """FakeRest whose open-market set the test can change mid-run."""

    def __init__(self) -> None:
        super().__init__()
        self.markets = [MARKET]

    async def get_open_markets(self, series_ticker: str) -> list[dict[str, Any]]:
        return [{"ticker": t} for t in self.markets]


async def test_discovery_syncs_ws_subscription(tmp_path: Path) -> None:
    """A newly-listed game must be subscribed without a restart; settled ones removed."""
    update_cmds: list[dict[str, Any]] = []
    got_add = asyncio.Event()
    got_delete = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        sub = json.loads(await ws.recv())
        assert sub["cmd"] == "subscribe"
        for channel, sid in (("orderbook_delta", 1), ("trade", 2)):
            ack = {"id": sub["id"], "type": "subscribed", "msg": {"channel": channel, "sid": sid}}
            await ws.send(json.dumps(ack))
        async for raw in ws:
            cmd = json.loads(raw)
            if cmd.get("cmd") == "update_subscription":
                update_cmds.append(cmd)
                if cmd["params"]["action"] == "add_markets":
                    got_add.set()
                if cmd["params"]["action"] == "delete_markets":
                    got_delete.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        cfg = RecorderConfig(
            data_dir=tmp_path,
            environment="test",
            series_tickers=("KXMLBGAME",),
            rest_url="http://127.0.0.1:9",
            ws_url=f"ws://127.0.0.1:{port}/trade-api/ws/v2",
            snapshot_interval_s=3600,
            discovery_interval_s=0.2,
            fsync_interval_s=0.0,
        )
        clock = CaptureClock()
        journals = JournalSet(tmp_path, clock, fsync_interval_s=0.0)
        rest = MutableRest()
        capture = KalshiCapture(cfg, clock, journals, rest, signer=None)

        run_task = asyncio.create_task(capture.run())
        try:
            await asyncio.sleep(0.3)  # let it connect and subscribe
            rest.markets = [MARKET, "KXMLBGAME-TEST-B"]
            await asyncio.wait_for(got_add.wait(), timeout=10)
            rest.markets = ["KXMLBGAME-TEST-B"]
            await asyncio.wait_for(got_delete.wait(), timeout=10)
        finally:
            capture.stop()
            await asyncio.wait_for(run_task, timeout=5)
            journals.close()
            await rest.aclose()

    adds = [c for c in update_cmds if c["params"]["action"] == "add_markets"]
    deletes = [c for c in update_cmds if c["params"]["action"] == "delete_markets"]
    assert adds[0]["params"]["market_tickers"] == ["KXMLBGAME-TEST-B"]
    assert adds[0]["params"]["sids"] == [1, 2]
    assert deletes[0]["params"]["market_tickers"] == [MARKET]
    # The newly-added market got an immediate REST snapshot (Doc 5 §2).
    assert "KXMLBGAME-TEST-B" in rest.orderbook_calls
