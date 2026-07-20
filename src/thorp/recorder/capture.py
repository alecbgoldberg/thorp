"""Kalshi capture orchestrator (Doc 5 §1-2, §6).

One asyncio task per concern, none blocking the others:

- WS loop: subscribe to book deltas + trades, journal every message, detect
  sequence gaps per subscription.
- Snapshot loop: periodic REST orderbook snapshots per tracked market
  (resync-safety anchor, Doc 5 §2), plus unconditionally on startup and gap.
- Discovery loop: poll open markets for the configured series, keep the WS
  subscription in sync as games are listed/settled.
- Housekeeping loop: clock resync (drift is logged, never silent) and
  journal throughput stats.

On a detected gap: journal a ``GapEventRecord``, fetch REST snapshots, and
force a WS reconnect — a fresh subscription re-delivers full snapshots, which
is Kalshi's documented recovery path. Never silently skip.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
from collections.abc import Coroutine
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import ClientConnection, connect

from thorp.common.clock import CaptureClock
from thorp.common.records import GapEventRecord, JsonDict, RawMessageRecord
from thorp.recorder.config import RecorderConfig
from thorp.recorder.journal import JournalSet
from thorp.recorder.kalshi.auth import KalshiSigner
from thorp.recorder.kalshi.normalize import (
    rest_orderbook_to_record,
    ws_delta_to_record,
    ws_snapshot_to_record,
    ws_trade_to_record,
)
from thorp.recorder.kalshi.rest import KalshiRestClient
from thorp.recorder.seq import SeqTracker

logger = logging.getLogger(__name__)

BOOK_CHANNEL = "orderbook_delta"
TRADE_CHANNEL = "trade"

VENUE = "kalshi"
DT_DELTAS = "book_deltas"
DT_SNAPSHOTS = "book_snapshots"
DT_TRADES = "trades"
DT_GAPS = "gap_events"
DT_MISC = "ws_misc"


class KalshiCapture:
    def __init__(
        self,
        cfg: RecorderConfig,
        clock: CaptureClock,
        journals: JournalSet,
        rest: KalshiRestClient,
        signer: KalshiSigner | None = None,
    ) -> None:
        self._cfg = cfg
        self._clock = clock
        self._journals = journals
        self._rest = rest
        self._signer = signer
        self._ws_sign_path = urlsplit(cfg.ws_url).path

        self._tickers: set[str] = set()
        self._seq = SeqTracker()
        self._sid_channel: dict[int, str] = {}
        self._channel_sid: dict[str, int] = {}
        self._last_seq_by_market: dict[str, int] = {}
        self._ws: ClientConnection | None = None
        self._stop_event = asyncio.Event()
        self._cmd_id = 0
        self._resyncing = False
        self._bg: set[asyncio.Task[None]] = set()

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        self._tickers = await self._discover()
        logger.info(
            "tracking %d open markets across series %s",
            len(self._tickers),
            list(self._cfg.series_tickers),
        )
        # Snapshot unconditionally on startup (Doc 5 §2).
        await self._rest_snapshot_all()

        tasks = [
            asyncio.create_task(self._ws_loop(), name="ws"),
            asyncio.create_task(self._snapshot_loop(), name="snapshots"),
            asyncio.create_task(self._discovery_loop(), name="discovery"),
            asyncio.create_task(self._housekeeping_loop(), name="housekeeping"),
        ]
        stop_wait = asyncio.create_task(self._stop_event.wait(), name="stop")
        try:
            done, _ = await asyncio.wait([*tasks, stop_wait], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stop_wait and task.exception() is not None:
                    raise task.exception()  # type: ignore[misc]  # narrowed by the check above
        finally:
            for task in [*tasks, stop_wait, *self._bg]:
                task.cancel()
            await asyncio.gather(*tasks, stop_wait, *self._bg, return_exceptions=True)

    # ------------------------------------------------------------- WS capture

    async def _ws_loop(self) -> None:
        backoff = 1.0
        while True:
            if not self._tickers:
                logger.info("no open markets to subscribe to; re-checking in 60s")
                await asyncio.sleep(60)
                continue
            try:
                headers = (
                    self._signer.headers("GET", self._ws_sign_path) if self._signer else None
                )
                async with connect(self._cfg.ws_url, additional_headers=headers) as ws:
                    logger.info("ws connected: %s", self._cfg.ws_url)
                    self._ws = ws
                    self._seq = SeqTracker()
                    self._sid_channel.clear()
                    self._channel_sid.clear()
                    await self._send_cmd(
                        ws,
                        "subscribe",
                        {
                            "channels": [BOOK_CHANNEL, TRADE_CHANNEL],
                            "market_tickers": sorted(self._tickers),
                        },
                    )
                    backoff = 1.0
                    async for raw in ws:
                        self._handle_message(raw, self._clock.now())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("ws disconnected (%r); reconnecting in %.1fs", exc, backoff)
            finally:
                self._ws = None
            await asyncio.sleep(backoff * (1 + random.random() / 2))
            backoff = min(backoff * 2, 30.0)

    async def _send_cmd(self, ws: ClientConnection, cmd: str, params: JsonDict) -> None:
        self._cmd_id += 1
        await ws.send(json.dumps({"id": self._cmd_id, "cmd": cmd, "params": params}))

    def _handle_message(self, raw: str | bytes, receive_ts: datetime) -> None:
        text = raw.decode() if isinstance(raw, bytes) else raw
        try:
            msg: JsonDict = json.loads(text)
        except ValueError:
            logger.error("unparseable ws message: %.200s", text)
            self._journal_misc({"unparseable": text}, receive_ts)
            return

        mtype = msg.get("type")
        if mtype == "subscribed":
            body = msg.get("msg") or {}
            sid, channel = int(body["sid"]), str(body["channel"])
            self._sid_channel[sid] = channel
            self._channel_sid[channel] = sid
            logger.info("subscribed channel=%s sid=%d", channel, sid)
        elif mtype == "orderbook_snapshot":
            body, sid, seq = msg["msg"], int(msg["sid"]), int(msg["seq"])
            # A snapshot is a fresh baseline for this subscription's seq.
            self._seq.reset(sid, seq)
            record = ws_snapshot_to_record(body, seq, receive_ts, self._clock.now())
            self._last_seq_by_market[record.market_key] = seq
            self._journals.write(VENUE, DT_SNAPSHOTS, record)
        elif mtype == "orderbook_delta":
            body, sid, seq = msg["msg"], int(msg["sid"]), int(msg["seq"])
            self._check_seq(sid, seq, receive_ts)
            delta = ws_delta_to_record(body, seq, receive_ts, self._clock.now())
            self._last_seq_by_market[delta.market_key] = seq
            self._journals.write(VENUE, DT_DELTAS, delta)
        elif mtype == "trade":
            body = msg["msg"]
            trade_seq = int(msg["seq"]) if "seq" in msg else None
            if trade_seq is not None and "sid" in msg:
                self._check_seq(int(msg["sid"]), trade_seq, receive_ts)
            trade = ws_trade_to_record(body, trade_seq, receive_ts, self._clock.now())
            self._journals.write(VENUE, DT_TRADES, trade)
        elif mtype == "error":
            logger.error("ws error message: %s", msg)
            self._journal_misc(msg, receive_ts)
        else:
            # Unknown type: never dropped (Doc 5 — the Recorder never misses data).
            self._journal_misc(msg, receive_ts)

    def _check_seq(self, sid: int, seq: int, receive_ts: datetime) -> None:
        gap = self._seq.observe(sid, seq)
        if gap is None:
            return
        channel = self._sid_channel.get(sid, f"sid={sid}")
        logger.warning(
            "sequence gap on %s: expected %d got %d (size %d) — resyncing",
            channel,
            gap.expected,
            gap.received,
            gap.size,
        )
        self._journals.write(
            VENUE,
            DT_GAPS,
            GapEventRecord(
                venue="kalshi",
                channel=channel,
                expected_seq=gap.expected,
                received_seq=gap.received,
                gap_size=gap.size,
                detected_at=receive_ts,
                action="reconnect+rest_snapshot",
            ),
        )
        self._spawn(self._resync_after_gap())

    async def _resync_after_gap(self) -> None:
        if self._resyncing:
            return
        self._resyncing = True
        try:
            ws = self._ws
            if ws is not None:
                # Reconnect forces a fresh subscription and full snapshots.
                await ws.close()
            await self._rest_snapshot_all()
        finally:
            self._resyncing = False

    def _journal_misc(self, msg: JsonDict, receive_ts: datetime) -> None:
        self._journals.write(
            VENUE,
            DT_MISC,
            RawMessageRecord(
                venue="kalshi",
                channel=str(msg.get("type")) if msg.get("type") else None,
                receive_ts=receive_ts,
                process_ts=self._clock.now(),
                raw=msg,
            ),
        )

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    # ---------------------------------------------------------- REST snapshots

    async def _snapshot_loop(self) -> None:
        while True:
            await asyncio.sleep(self._cfg.snapshot_interval_s)
            await self._rest_snapshot_all()

    async def _rest_snapshot_all(self) -> None:
        for ticker in sorted(self._tickers):
            try:
                payload = await self._rest.get_orderbook(ticker)
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("REST snapshot failed for %s: %r", ticker, exc)
                continue
            receive_ts = self._clock.now()
            record = rest_orderbook_to_record(
                payload,
                ticker,
                self._last_seq_by_market.get(ticker),
                receive_ts,
                self._clock.now(),
            )
            self._journals.write(VENUE, DT_SNAPSHOTS, record)
            await asyncio.sleep(0.05)  # stay far under Basic-tier read limits

    # -------------------------------------------------------- market discovery

    async def _discovery_loop(self) -> None:
        while True:
            await asyncio.sleep(self._cfg.discovery_interval_s)
            try:
                fresh = await self._discover()
            except (httpx.HTTPError, OSError) as exc:
                # Transient REST failure must not wipe live subscriptions.
                logger.warning("market discovery failed: %r", exc)
                continue
            added, removed = fresh - self._tickers, self._tickers - fresh
            if not added and not removed:
                continue
            logger.info("market set changed: +%d -%d", len(added), len(removed))
            self._tickers = fresh
            ws = self._ws
            if ws is not None and self._channel_sid:
                sids = sorted(self._channel_sid.values())
                if added:
                    await self._send_cmd(
                        ws,
                        "update_subscription",
                        {"sids": sids, "market_tickers": sorted(added), "action": "add_markets"},
                    )
                if removed:
                    await self._send_cmd(
                        ws,
                        "update_subscription",
                        {
                            "sids": sids,
                            "market_tickers": sorted(removed),
                            "action": "delete_markets",
                        },
                    )
            if added:
                with contextlib.suppress(Exception):
                    await self._rest_snapshot_markets(sorted(added))

    async def _rest_snapshot_markets(self, tickers: list[str]) -> None:
        keep = self._tickers
        self._tickers = set(tickers)
        try:
            await self._rest_snapshot_all()
        finally:
            self._tickers = keep

    async def _discover(self) -> set[str]:
        tickers: set[str] = set()
        for series in self._cfg.series_tickers:
            markets = await self._rest.get_open_markets(series)
            tickers.update(str(m["ticker"]) for m in markets)
        return tickers

    # ------------------------------------------------------------ housekeeping

    async def _housekeeping_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            drift_s = self._clock.resync()
            level = logging.WARNING if abs(drift_s) > 0.05 else logging.DEBUG
            logger.log(level, "clock resync: drift %.6fs", drift_s)
            logger.info("journal stats: %s", self._journals.stats())
