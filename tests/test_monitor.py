"""Monitor: mark-to-mid P&L math, tolerant file reading, and the state endpoint."""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

from thorp.monitor.demo import DemoEngine, _fee, _Pos
from thorp.monitor.model import build_view, unrealized_pnl
from thorp.monitor.reader import read_status, tail_events
from thorp.monitor.server import MonitorSource, build_server
from thorp.telemetry.events import (
    EngineStatus,
    FillEvent,
    MarketMark,
    OpenOrder,
    OrderState,
    PositionMark,
    RunMode,
)
from thorp.telemetry.writer import EventLog, StatusWriter

NOW = datetime(2026, 7, 20, 18, 0, 0, tzinfo=UTC)


def pos(net: int, avg: str) -> PositionMark:
    return PositionMark(
        market_key="M", correlated_group="G", net_contracts=net,
        avg_entry=Decimal(avg), realized_pnl=Decimal(0),
    )


def test_unrealized_long_and_short() -> None:
    # Long 10 @ 0.40, mid 0.55 -> +$1.50
    assert unrealized_pnl(pos(10, "0.40"), Decimal("0.55")) == Decimal("1.50")
    # Short 10 @ 0.40 (mid fell to 0.30) -> +$1.00
    assert unrealized_pnl(pos(-10, "0.40"), Decimal("0.30")) == Decimal("1.00")
    # Short that moved against us (mid rose) -> negative
    assert unrealized_pnl(pos(-10, "0.40"), Decimal("0.50")) == Decimal("-1.00")


def test_unrealized_none_when_flat_or_no_mark() -> None:
    assert unrealized_pnl(pos(0, "0"), Decimal("0.5")) is None
    assert unrealized_pnl(pos(5, "0.40"), None) is None


def test_mid_fallback_from_bid_ask() -> None:
    status = EngineStatus(
        mode=RunMode.SIMULATION, updated_at=NOW, started_at=NOW,
        markets=[MarketMark(market_key="M", bid=Decimal("0.40"), ask=Decimal("0.44"), mid=None)],
        positions=[pos(10, "0.40")],
    )
    view = build_view(status, [], NOW)
    assert view["positions"][0]["mid"] == 0.42
    assert view["positions"][0]["unrealized"] == 0.2  # 10 * (0.42 - 0.40)


def test_build_view_aggregates_pnl_and_orders() -> None:
    status = EngineStatus(
        mode=RunMode.SIMULATION, updated_at=NOW, started_at=NOW - timedelta(minutes=5),
        markets=[MarketMark(market_key="M", bid=None, ask=None, mid=Decimal("0.60"))],
        positions=[
            PositionMark(market_key="M", correlated_group="G", net_contracts=10,
                         avg_entry=Decimal("0.50"), realized_pnl=Decimal("2.00")),
        ],
        open_orders=[
            OpenOrder(order_id="o1", market_key="M", correlated_group="G", side="buy_yes",
                      price=Decimal("0.55"), size=5, filled=1, state=OrderState.ACKNOWLEDGED,
                      submitted_at=NOW - timedelta(seconds=30)),
        ],
        fees_paid=Decimal("0.13"),
    )
    view = build_view(status, [], NOW)
    assert view["connected"] is True
    assert view["pnl"]["realized"] == 2.0
    assert view["pnl"]["unrealized"] == 1.0  # 10 * (0.60 - 0.50)
    assert view["pnl"]["net"] == 3.0
    assert view["pnl"]["fees_paid"] == 0.13
    assert view["open_orders"][0]["remaining"] == 4
    assert view["open_orders"][0]["age_s"] == 30.0
    assert view["uptime_s"] == 300.0


def test_build_view_disconnected_without_status() -> None:
    view = build_view(None, [], NOW)
    assert view["connected"] is False


def test_staleness_flag() -> None:
    status = EngineStatus(mode=RunMode.SIMULATION, updated_at=NOW - timedelta(seconds=9),
                          started_at=NOW)
    view = build_view(status, [], NOW)
    assert view["stale"] is True and view["staleness_s"] >= 9


def test_reader_round_trips_via_writers(tmp_path: Path) -> None:
    StatusWriter(tmp_path / "status.json").write(
        EngineStatus(mode=RunMode.SIMULATION, updated_at=NOW, started_at=NOW)
    )
    log = EventLog(tmp_path / "events.jsonl")
    log.append(FillEvent(seq=1, ts=NOW, fill_id="f1", order_id="o1", market_key="M",
                         correlated_group="G", side="buy_yes", price=Decimal("0.4"), size=3,
                         fee=Decimal("0.02"), liquidity="taker"))
    log.close()

    status = read_status(tmp_path / "status.json")
    assert status is not None and status.mode == RunMode.SIMULATION
    events = tail_events(tmp_path / "events.jsonl")
    assert len(events) == 1 and isinstance(events[0], FillEvent)


def test_reader_tolerates_missing_files(tmp_path: Path) -> None:
    assert read_status(tmp_path / "nope.json") is None
    assert tail_events(tmp_path / "nope.jsonl") == []


def test_reader_skips_truncated_final_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    good = FillEvent(seq=1, ts=NOW, fill_id="f1", order_id="o1", market_key="M",
                     correlated_group="G", side="buy_yes", price=Decimal("0.4"), size=1,
                     fee=Decimal("0.01"), liquidity="maker")
    path.write_text(good.model_dump_json() + "\n" + '{"event_type":"fill","seq":2,')  # torn
    events = tail_events(path)
    assert len(events) == 1 and events[0].seq == 1


def test_state_endpoint_serves_view(tmp_path: Path) -> None:
    StatusWriter(tmp_path / "status.json").write(
        EngineStatus(mode=RunMode.SIMULATION, updated_at=datetime.now(UTC),
                     started_at=datetime.now(UTC))
    )
    source = MonitorSource(tmp_path / "status.json", tmp_path / "events.jsonl")
    server = build_server("127.0.0.1", 0, source)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        page = httpx.get(f"http://127.0.0.1:{port}/")
        assert page.status_code == 200 and "THORP" in page.text
        state = httpx.get(f"http://127.0.0.1:{port}/api/state").json()
        assert state["connected"] is True and state["mode"] == "SIMULATION"
        assert httpx.get(f"http://127.0.0.1:{port}/healthz").text == "ok"
        assert httpx.get(f"http://127.0.0.1:{port}/nope").status_code == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_fee_matches_kalshi_formula() -> None:
    # round_up(0.07 * 100 * 0.5 * 0.5) = round_up(1.75) = 1.75
    assert _fee(Decimal("0.50"), 100) == Decimal("1.75")


def test_demo_apply_fill_accounting(tmp_path: Path) -> None:
    eng = DemoEngine(session_dir=tmp_path, seed=1)
    # Fresh position key (DemoEngine seeds _pos from its own market set).
    eng._pos["X"] = _Pos()
    # Buy 10 @ 0.40, buy 10 @ 0.50 -> avg 0.45, net 20
    eng._apply_fill("X", "buy_yes", Decimal("0.40"), 10)
    eng._apply_fill("X", "buy_yes", Decimal("0.50"), 10)
    px = eng._pos["X"]
    assert px.net == 20 and px.avg == Decimal("0.45")
    # Sell 20 @ 0.60 -> realized 20 * (0.60 - 0.45) = 3.00, flat
    eng._apply_fill("X", "sell_yes", Decimal("0.60"), 20)
    assert px.net == 0 and px.realized == Decimal("3.00")
    eng.close()


def test_demo_tick_writes_valid_files(tmp_path: Path) -> None:
    eng = DemoEngine(session_dir=tmp_path, seed=3)
    eng._write_status(datetime.now(UTC))
    for _ in range(40):
        eng.tick()
    eng.close()

    status = read_status(tmp_path / "status.json")
    assert status is not None and status.mode == RunMode.SIMULATION
    # Event log is valid JSONL end to end.
    for line in (tmp_path / "events.jsonl").read_text().splitlines():
        json.loads(line)
    view = build_view(status, tail_events(tmp_path / "events.jsonl"), datetime.now(UTC))
    assert view["connected"] is True
    assert set(view["pnl"]) == {"realized", "unrealized", "net", "fees_paid"}
