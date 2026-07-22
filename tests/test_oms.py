"""OMS: revised state machine, fill dedup, rate limits, reservation release."""

from decimal import Decimal

import pytest

from thorp.engine.oms import (
    OMS,
    RateLimited,
    ReconciliationBreak,
    TokenBucket,
    client_order_id,
)
from thorp.engine.state import RiskState
from thorp.engine.types import ApprovedIntent, OrderIntent
from thorp.telemetry.events import OrderState


def intent(iid: str = "i1", strat: str = "s", group: str = "G", reason: str = "r") -> OrderIntent:
    return OrderIntent(strat, "M", group, "buy_yes", Decimal("0.50"), 10, reason, iid)


def reserved_state() -> RiskState:
    s = RiskState()
    s.market_to_group["M"] = "G"
    s.reserve(intent(), 10)  # RiskEngine would have reserved this at approval
    return s


def submit(oms: OMS, size: int = 10) -> str:
    rec = oms.submit(ApprovedIntent(intent(), size))
    return rec.client_order_id


def test_client_order_id_deterministic_and_nonce_varies() -> None:
    assert client_order_id("s", "G", "r", 1) == client_order_id("s", "G", "r", 1)
    assert client_order_id("s", "G", "r", 1) != client_order_id("s", "G", "r", 2)


def test_happy_path_new_ack_partial_filled_releases_reservation() -> None:
    s = reserved_state()
    oms = OMS(s)
    coid = submit(oms)
    assert oms.get(coid).state == OrderState.NEW
    oms.on_ack(coid)
    assert oms.get(coid).state == OrderState.ACKNOWLEDGED
    oms.on_fill(coid, "f1", cumulative_filled=4)
    assert oms.get(coid).state == OrderState.PARTIALLY_FILLED
    assert s.has_reservation("i1")  # still resting
    oms.on_fill(coid, "f2", cumulative_filled=10)
    assert oms.get(coid).state == OrderState.FILLED
    assert not s.has_reservation("i1")  # released on terminal


def test_duplicate_fill_id_is_noop() -> None:
    oms = OMS(reserved_state())
    coid = submit(oms)
    oms.on_ack(coid)
    oms.on_fill(coid, "f1", cumulative_filled=4)
    oms.on_fill(coid, "f1", cumulative_filled=4)  # redelivery
    assert oms.get(coid).filled_qty == 4  # not double-counted


def test_pending_cancel_then_fill_is_legal() -> None:
    """Direct regression for the Opus-found mis-flagged race (Doc 6 §2)."""
    oms = OMS(reserved_state())
    coid = submit(oms)
    oms.on_ack(coid)
    oms.request_cancel(coid)
    assert oms.get(coid).state == OrderState.PENDING_CANCEL
    oms.on_fill(coid, "f1", cumulative_filled=10)  # filled before cancel processed
    assert oms.get(coid).state == OrderState.FILLED  # legal, not a break


def test_fill_exceeding_resting_size_is_a_break() -> None:
    oms = OMS(reserved_state())
    coid = submit(oms)
    oms.on_ack(coid)
    with pytest.raises(ReconciliationBreak):
        oms.on_fill(coid, "f1", cumulative_filled=11)  # > resting 10


def test_duplicate_terminal_agrees_noop_disagrees_break() -> None:
    oms = OMS(reserved_state())
    coid = submit(oms)
    oms.on_ack(coid)
    oms.on_cancelled(coid)
    oms.on_cancelled(coid)  # agrees -> no-op
    assert oms.get(coid).state == OrderState.CANCELLED
    with pytest.raises(ReconciliationBreak):
        oms.on_rejected(coid)  # disagrees with CANCELLED


def test_reject_after_ack_is_terminal_and_releases() -> None:
    s = reserved_state()
    oms = OMS(s)
    coid = submit(oms)
    oms.on_ack(coid)
    oms.on_rejected(coid)  # e.g. self-match / market close
    assert oms.get(coid).state == OrderState.REJECTED
    assert not s.has_reservation("i1")


def test_rate_limit_blocks_and_frees_reservation() -> None:
    t = [0.0]
    s = RiskState()
    s.market_to_group["M"] = "G"
    oms = OMS(s, max_orders_per_s=1.0, clock=lambda: t[0])
    s.reserve(intent("iA"), 10)
    oms.submit(ApprovedIntent(intent("iA"), 10))  # consumes the token
    s.reserve(intent("iB"), 10)
    with pytest.raises(RateLimited):
        oms.submit(ApprovedIntent(intent("iB"), 10))
    assert not s.has_reservation("iB")  # blocked submit must not leave it reserved


def test_token_bucket_refills_over_time() -> None:
    t = [0.0]
    b = TokenBucket(2.0, clock=lambda: t[0])
    assert b.take() and b.take()  # capacity 2
    assert not b.take()
    t[0] = 1.0  # +1s -> +2 tokens
    assert b.take()
