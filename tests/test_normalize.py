"""Kalshi yes/no book -> Doc 5 bid/ask schema, hand-computed cases (Doc 6 §2)."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from thorp.recorder.kalshi.normalize import (
    cents_to_dollars,
    parse_exchange_ts,
    rest_orderbook_to_record,
    ws_delta_to_record,
    ws_snapshot_to_record,
    ws_trade_to_record,
)

RECV = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
PROC = datetime(2026, 7, 20, 12, 0, 0, 150, tzinfo=UTC)


def test_cents_to_dollars_exact() -> None:
    assert cents_to_dollars(43) == Decimal("0.43")
    assert cents_to_dollars(1) == Decimal("0.01")
    # Sub-cent ticks near the extremes (tapered_deci_cent, Doc 1 §1.1) stay exact.
    assert cents_to_dollars(0.5) == Decimal("0.005")


def test_parse_exchange_ts_seconds_and_millis() -> None:
    assert parse_exchange_ts(None) is None
    seconds = parse_exchange_ts(1_789_000_000)
    millis = parse_exchange_ts(1_789_000_000_500)
    assert seconds == datetime.fromtimestamp(1_789_000_000, tz=UTC)
    assert millis is not None and abs((millis - seconds).total_seconds() - 0.5) < 1e-9  # type: ignore[arg-type]


def test_snapshot_yes_no_to_bid_ask() -> None:
    msg = {
        "market_ticker": "KXMLBGAME-TEST",
        "yes": [[39, 50], [40, 100]],  # buy-YES resting orders (bids)
        "no": [[55, 25], [58, 10]],  # buy-NO at 55 == ask on YES at 45
    }
    record = ws_snapshot_to_record(msg, seq=7, receive_ts=RECV, process_ts=PROC)
    assert record.market_key == "KXMLBGAME-TEST"
    assert record.seq == 7
    assert record.source == "ws"
    assert record.bids == [(Decimal("0.40"), 100), (Decimal("0.39"), 50)]  # descending
    assert record.asks == [(Decimal("0.42"), 10), (Decimal("0.45"), 25)]  # ascending
    assert record.raw == msg


def test_delta_no_side_maps_to_ask() -> None:
    msg = {"market_ticker": "T", "price": 55, "delta": -10, "side": "no"}
    record = ws_delta_to_record(msg, seq=3, receive_ts=RECV, process_ts=PROC)
    assert record.side == "ask"
    assert record.price == Decimal("0.45")
    assert record.size == -10


def test_delta_yes_side_maps_to_bid() -> None:
    msg = {"market_ticker": "T", "price": 40, "delta": 100, "side": "yes"}
    record = ws_delta_to_record(msg, seq=4, receive_ts=RECV, process_ts=PROC)
    assert record.side == "bid"
    assert record.price == Decimal("0.40")
    assert record.size == 100


def test_trade_taker_side_mapping() -> None:
    msg = {
        "market_ticker": "T",
        "yes_price": 41,
        "no_price": 59,
        "count": 7,
        "taker_side": "no",
        "ts": 1_789_000_000,
    }
    record = ws_trade_to_record(msg, seq=None, receive_ts=RECV, process_ts=PROC)
    assert record.price == Decimal("0.41")
    assert record.size == 7
    assert record.taker_side == "sell"  # NO taker == selling YES
    assert record.exchange_ts == datetime.fromtimestamp(1_789_000_000, tz=UTC)


def test_unexpected_side_or_taker_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="side"):
        ws_delta_to_record(
            {"market_ticker": "T", "price": 40, "delta": 1, "side": "maybe"},
            seq=1,
            receive_ts=RECV,
            process_ts=PROC,
        )
    with pytest.raises(ValueError, match="taker_side"):
        ws_trade_to_record(
            {"market_ticker": "T", "yes_price": 41, "count": 1, "taker_side": "both"},
            seq=None,
            receive_ts=RECV,
            process_ts=PROC,
        )


def test_rest_orderbook_handles_empty_sides() -> None:
    payload = {"orderbook": {"yes": None, "no": [[97, 5]]}}
    record = rest_orderbook_to_record(
        payload, "T", last_ws_seq=42, receive_ts=RECV, process_ts=PROC
    )
    assert record.source == "rest"
    assert record.seq == 42
    assert record.bids == []
    assert record.asks == [(Decimal("0.03"), 5)]


def test_json_line_round_trip_preserves_decimal_as_string() -> None:
    msg = {"market_ticker": "T", "price": 40, "delta": 1, "side": "yes"}
    record = ws_delta_to_record(msg, seq=1, receive_ts=RECV, process_ts=PROC)
    parsed = json.loads(record.to_json_line())
    assert parsed["price"] == "0.4"  # exact decimal string, never a float
    assert parsed["record_type"] == "book_delta"
    assert parsed["raw"]["side"] == "yes"
