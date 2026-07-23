"""Real-time Kalshi order-book stream (WS) — replaces 5s REST snapshots.

Maintains a live ``LiveBook`` per market from the ``orderbook_delta`` channel, so
the engine reads the *current* book (updated on every tick) instead of a poll
snapshot. Discovery (the market list) and volume/OI stay REST — the WS is
book-only. A sequence gap forces a reconnect (fresh snapshots), never a silent
skip. Order *placement* is still REST (Kalshi has no WS order entry); this is the
market-data half.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import UTC, datetime
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect

from thorp.recorder.kalshi.auth import KalshiSigner
from thorp.recorder.seq import SeqTracker
from thorp.stream.book import Level, LiveBook

logger = logging.getLogger("thorp.stream")


class KalshiBookStream:
    def __init__(self, ws_url: str, signer: KalshiSigner | None = None) -> None:
        self._ws_url = ws_url
        self._signer = signer
        self._sign_path = urlsplit(ws_url).path
        self._books: dict[str, LiveBook] = {}
        self._updated: dict[str, datetime] = {}
        self._desired: set[str] = set()
        self._subscribed: frozenset[str] = frozenset()
        self._seq = SeqTracker()
        self._ws: ClientConnection | None = None
        self._cmd_id = 0
        self._stop = asyncio.Event()

    # -- public API used by the collector/engine ---------------------------
    def subscribe(self, tickers: list[str]) -> None:
        self._desired = set(tickers)

    def book(self, ticker: str) -> LiveBook | None:
        return self._books.get(ticker)

    def bbo(self, ticker: str) -> tuple[object, object, object]:
        b = self._books.get(ticker)
        return b.bbo() if b else (None, None, None)

    def ladder(self, ticker: str, top: int = 10) -> tuple[list[Level], list[Level]]:
        b = self._books.get(ticker)
        return b.ladder(top) if b else ([], [])

    def age_s(self, ticker: str, now: datetime | None = None) -> float:
        u = self._updated.get(ticker)
        if u is None:
            return float("inf")
        return ((now or datetime.now(UTC)) - u).total_seconds()

    def ready(self) -> int:
        return len(self._books)

    def stop(self) -> None:
        self._stop.set()

    # -- WS lifecycle ------------------------------------------------------
    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            if not self._desired:
                await asyncio.sleep(1.0)
                continue
            try:
                headers = self._signer.headers("GET", self._sign_path) if self._signer else None
                async with connect(self._ws_url, additional_headers=headers) as ws:
                    self._ws = ws
                    self._seq = SeqTracker()
                    await self._resubscribe(ws)
                    backoff = 1.0
                    async for raw in ws:
                        if self._handle(raw) == "resync":
                            break  # reconnect -> fresh snapshots
                        if self._desired != set(self._subscribed):
                            break  # ticker set changed -> reconnect with new set
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("kalshi WS error (%r); reconnecting in %.1fs", exc, backoff)
            finally:
                self._ws = None
            if not self._stop.is_set():
                await asyncio.sleep(backoff * (1 + random.random() / 2))
                backoff = min(backoff * 2, 30.0)

    async def _resubscribe(self, ws: ClientConnection) -> None:
        self._subscribed = frozenset(self._desired)
        self._cmd_id += 1
        await ws.send(json.dumps({
            "id": self._cmd_id, "cmd": "subscribe",
            "params": {"channels": ["orderbook_delta"],
                       "market_tickers": sorted(self._subscribed)},
        }))

    def _handle(self, raw: str | bytes) -> str | None:
        text = raw.decode() if isinstance(raw, bytes) else raw
        try:
            m = json.loads(text)
        except ValueError:
            return None
        mtype = m.get("type")
        if mtype == "orderbook_snapshot":
            body, sid, seq = m["msg"], int(m["sid"]), int(m["seq"])
            self._seq.reset(sid, seq)
            ticker = str(body["market_ticker"])
            book = self._books.setdefault(ticker, LiveBook())
            book.apply_snapshot(body.get("yes_dollars_fp"), body.get("no_dollars_fp"))
            self._updated[ticker] = datetime.now(UTC)
        elif mtype == "orderbook_delta":
            body, sid, seq = m["msg"], int(m["sid"]), int(m["seq"])
            if self._seq.observe(sid, seq) is not None:
                logger.warning("kalshi WS seq gap on sid %d — resyncing", sid)
                return "resync"
            ticker = str(body["market_ticker"])
            book = self._books.setdefault(ticker, LiveBook())
            book.apply_delta(str(body["side"]), body.get("price_dollars"), body.get("delta_fp"))
            self._updated[ticker] = datetime.now(UTC)
        return None
