"""Capture-record schemas (Doc 5 §2).

Every market-data record carries the three-timestamp discipline of Doc 5 §4
(``exchange_ts`` / ``receive_ts`` / ``process_ts``), never collapsed into one.
Prices are ``Decimal`` dollars (0 < p < 1 for contract prices); pydantic
serializes them as exact strings in JSON, never floats.

Records additionally keep ``raw`` — the verbatim venue message — so a bug in
our normalization (e.g. the yes/no -> bid/ask mapping) is recoverable from the
journal instead of silently corrupting the corpus. Storage is cheap (Doc 5 §5);
lost fidelity is not. ``raw`` may be dropped at Parquet compaction time.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Venue = Literal["kalshi", "polymarket"]
BookSide = Literal["bid", "ask"]
JsonDict = dict[str, Any]

# One price level: (price in dollars, resting contracts).
BookLevel = tuple[Decimal, int]


class BaseRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def to_json_line(self) -> str:
        return self.model_dump_json()


class BookDeltaRecord(BaseRecord):
    """A single price-level change on one side of the book."""

    record_type: Literal["book_delta"] = "book_delta"
    venue: Venue
    market_key: str
    seq: int
    side: BookSide
    price: Decimal
    size: int  # signed change in resting contracts at this level
    exchange_ts: datetime | None = None
    receive_ts: datetime
    process_ts: datetime
    raw: JsonDict | None = None


class TradeRecord(BaseRecord):
    record_type: Literal["trade"] = "trade"
    venue: Venue
    market_key: str
    seq: int | None = None
    price: Decimal  # YES price in dollars
    size: int
    taker_side: Literal["buy", "sell"]  # of YES: Kalshi taker_side yes->buy, no->sell
    exchange_ts: datetime | None = None
    receive_ts: datetime
    process_ts: datetime
    raw: JsonDict | None = None


class BookSnapshotRecord(BaseRecord):
    """Full book state — the anchor a resync-from-gap or replay starts from.

    ``seq`` is the venue sequence the snapshot was taken at. WS snapshots carry
    their own seq; REST snapshots are anchored to the last WS seq observed for
    the market at fetch time (``None`` if no WS message has been seen yet).
    """

    record_type: Literal["book_snapshot"] = "book_snapshot"
    venue: Venue
    market_key: str
    seq: int | None
    source: Literal["ws", "rest"]
    bids: list[BookLevel]  # descending price
    asks: list[BookLevel]  # ascending price
    exchange_ts: datetime | None = None
    receive_ts: datetime
    process_ts: datetime
    raw: JsonDict | None = None


class GapEventRecord(BaseRecord):
    """Logged whenever a stream's seq breaks monotonic +1 (Doc 5 §6).

    Kalshi's WS seq is per-subscription, not per-market, so ``market_key`` is
    None for subscription-scoped gaps. ``gap_size`` < 0 flags a duplicate or
    out-of-order message rather than missed ones.
    """

    record_type: Literal["gap_event"] = "gap_event"
    venue: Venue
    channel: str
    market_key: str | None = None
    expected_seq: int
    received_seq: int
    gap_size: int
    detected_at: datetime
    action: str  # e.g. "reconnect+rest_snapshot"


class RawMessageRecord(BaseRecord):
    """Fallback journal entry for any venue message we don't recognize.

    The Recorder's one job is to never miss data (Doc 5): an unknown message
    type is journaled verbatim, not dropped.
    """

    record_type: Literal["raw_message"] = "raw_message"
    venue: Venue
    channel: str | None = None
    receive_ts: datetime
    process_ts: datetime
    raw: JsonDict


class OddsRecord(BaseRecord):
    """Sportsbook consensus odds observation (Doc 5 §2). Captured from Week 2."""

    record_type: Literal["odds"] = "odds"
    book: str
    market_key: str
    market_type: Literal["h2h", "spread", "total"]
    side: str
    price: str  # stored exactly as fetched (american or decimal), per Doc 5 §2
    line: Decimal | None = None
    fetched_ts: datetime
    raw: JsonDict | None = None
