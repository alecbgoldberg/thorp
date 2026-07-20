"""Kalshi wire messages -> Doc 5 §2 records.

Kalshi expresses its book as two arrays of *bids*: resting buy-YES orders
("yes" side) and resting buy-NO orders ("no" side), both as
``[price_cents, contracts]``. The Doc 5 schema is venue-neutral bid/ask on the
YES contract, so:

    yes-bid at p cents            -> bid  at $p/100
    no-bid  at q cents            -> ask  at $(100-q)/100   (buying NO at q ==
                                     standing ready to sell YES at 100-q)

This mapping is exactly the kind of transformation where silent corruption
hides, so every record retains the verbatim message in ``raw`` and the mapping
has hand-computed unit tests (Doc 6 §2 book-maintenance row).

[VERIFY on first live capture] Field names/shapes here follow docs.kalshi.com
as researched in Doc 1 §1.1 but have not yet been checked against live demo
traffic; unknown message types are journaled verbatim rather than dropped, so
a mismatch is recoverable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from thorp.common.records import (
    BookDeltaRecord,
    BookLevel,
    BookSnapshotRecord,
    JsonDict,
    TradeRecord,
)


def cents_to_dollars(cents: Any) -> Decimal:
    """Exact cents -> dollars. Accepts int or sub-cent decimal cents.

    Kalshi may report sub-cent ticks near 1¢/99¢ (``tapered_deci_cent``,
    Doc 1 §1.1 [VERIFY]); ``Decimal(str(...))`` keeps those exact too.
    """
    return Decimal(str(cents)) / 100


def parse_exchange_ts(value: Any) -> datetime | None:
    """Epoch seconds or milliseconds -> aware UTC datetime."""
    if value is None:
        return None
    ts = float(value)
    if ts > 1e12:  # milliseconds
        ts /= 1000
    return datetime.fromtimestamp(ts, tz=UTC)


def _levels(raw_levels: list[Any] | None, side: Literal["yes", "no"]) -> list[BookLevel]:
    levels: list[BookLevel] = []
    for price_cents, size in raw_levels or []:
        price = (
            cents_to_dollars(price_cents)
            if side == "yes"
            else Decimal(1) - cents_to_dollars(price_cents)
        )
        levels.append((price, int(size)))
    # Deterministic order: bids descending (best first), asks ascending.
    levels.sort(key=lambda lv: lv[0], reverse=side == "yes")
    return levels


def ws_snapshot_to_record(
    msg: JsonDict, seq: int, receive_ts: datetime, process_ts: datetime
) -> BookSnapshotRecord:
    return BookSnapshotRecord(
        venue="kalshi",
        market_key=str(msg["market_ticker"]),
        seq=seq,
        source="ws",
        bids=_levels(msg.get("yes"), "yes"),
        asks=_levels(msg.get("no"), "no"),
        exchange_ts=parse_exchange_ts(msg.get("ts")),
        receive_ts=receive_ts,
        process_ts=process_ts,
        raw=msg,
    )


def rest_orderbook_to_record(
    payload: JsonDict,
    market_ticker: str,
    last_ws_seq: int | None,
    receive_ts: datetime,
    process_ts: datetime,
) -> BookSnapshotRecord:
    book = payload.get("orderbook") or {}
    return BookSnapshotRecord(
        venue="kalshi",
        market_key=market_ticker,
        seq=last_ws_seq,
        source="rest",
        bids=_levels(book.get("yes"), "yes"),
        asks=_levels(book.get("no"), "no"),
        receive_ts=receive_ts,
        process_ts=process_ts,
        raw=payload,
    )


def ws_delta_to_record(
    msg: JsonDict, seq: int, receive_ts: datetime, process_ts: datetime
) -> BookDeltaRecord:
    kalshi_side = msg["side"]
    if kalshi_side not in ("yes", "no"):
        raise ValueError(f"unexpected kalshi book side: {kalshi_side!r}")
    price = (
        cents_to_dollars(msg["price"])
        if kalshi_side == "yes"
        else Decimal(1) - cents_to_dollars(msg["price"])
    )
    return BookDeltaRecord(
        venue="kalshi",
        market_key=str(msg["market_ticker"]),
        seq=seq,
        side="bid" if kalshi_side == "yes" else "ask",
        price=price,
        size=int(msg["delta"]),
        exchange_ts=parse_exchange_ts(msg.get("ts")),
        receive_ts=receive_ts,
        process_ts=process_ts,
        raw=msg,
    )


def ws_trade_to_record(
    msg: JsonDict, seq: int | None, receive_ts: datetime, process_ts: datetime
) -> TradeRecord:
    taker = msg.get("taker_side")
    if taker not in ("yes", "no"):
        raise ValueError(f"unexpected kalshi taker_side: {taker!r}")
    return TradeRecord(
        venue="kalshi",
        market_key=str(msg["market_ticker"]),
        seq=seq,
        price=cents_to_dollars(msg["yes_price"]),
        size=int(msg["count"]),
        taker_side="buy" if taker == "yes" else "sell",
        exchange_ts=parse_exchange_ts(msg.get("ts")),
        receive_ts=receive_ts,
        process_ts=process_ts,
        raw=msg,
    )
