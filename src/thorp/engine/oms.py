"""Order Management System (Doc 3 §3.6) — single chokepoint for every order.

Revised per the Opus review:
- Explicit ``PENDING_CANCEL``; a fill arriving for a PENDING_CANCEL order is a
  **legal** transition (exchange filled before processing our cancel), not a
  break.
- Fills are **deduplicated by exchange fill-id** and reconciled against Kalshi's
  **cumulative** filled quantity, never summed from deltas (redelivery-safe).
- A late/duplicate terminal message that **agrees** with known state is a no-op;
  one that **disagrees** raises a reconciliation break.
- ``client_order_id`` = hash(strategy, group, reason, nonce), nonce a monotonic
  per-session counter (client-enforced uniqueness); resubmitting the same id is
  treated as a retry of the original, not a new order.

On any terminal transition the OMS **releases the RiskState reservation** for the
order, reconciling in-flight exposure against reality (Doc 4 §2).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from thorp.engine.state import RiskState
from thorp.engine.types import ApprovedIntent, ModifiedIntent, OrderIntent
from thorp.telemetry.events import TERMINAL_STATES, OrderState


class ReconciliationBreak(Exception):
    """Raised when observed exchange state contradicts internal state (Doc 4 §7).
    The engine must cancel-all then halt; never trade through it."""


class RateLimited(Exception):
    """Raised when a submit/cancel would exceed the local rate budget (Doc 4 §4)."""


def client_order_id(strategy: str, group: str, reason: str, nonce: int) -> str:
    raw = f"{strategy}|{group}|{reason}|{nonce}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


class TokenBucket:
    def __init__(self, rate_per_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate = rate_per_s
        self._capacity = max(1.0, rate_per_s)
        self._tokens = self._capacity
        self._clock = clock
        self._last = clock()

    def take(self) -> bool:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


@dataclass
class OrderRecord:
    client_order_id: str
    intent: OrderIntent
    resting_size: int
    state: OrderState = OrderState.NEW
    filled_qty: int = 0
    seen_fill_ids: set[str] = field(default_factory=set)

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


class OMS:
    def __init__(
        self,
        state: RiskState,
        max_orders_per_s: float = 2.0,
        max_cancels_per_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = state
        self._orders: dict[str, OrderRecord] = {}
        self._nonce = 0
        self._order_bucket = TokenBucket(max_orders_per_s, clock)
        self._cancel_bucket = TokenBucket(max_cancels_per_s, clock)

    def _next_nonce(self) -> int:
        self._nonce += 1
        return self._nonce

    def submit(self, approved: ApprovedIntent | ModifiedIntent) -> OrderRecord:
        intent = approved.intent
        coid = client_order_id(
            intent.strategy_name, intent.correlated_group, intent.reason, self._next_nonce()
        )
        if coid in self._orders:  # retry of an identical id -> original, not new
            return self._orders[coid]
        if not self._order_bucket.take():
            self._state.release(intent.intent_id)  # never left reserved on a blocked submit
            raise RateLimited("order rate budget exceeded")
        record = OrderRecord(coid, intent, resting_size=approved.approved_size)
        self._orders[coid] = record
        return record

    def get(self, coid: str) -> OrderRecord:
        return self._orders[coid]

    # ---- exchange callbacks ----------------------------------------------
    def on_ack(self, coid: str) -> None:
        order = self._orders[coid]
        if order.state == OrderState.NEW:
            order.state = OrderState.ACKNOWLEDGED

    def request_cancel(self, coid: str) -> None:
        order = self._orders[coid]
        if order.terminal:
            return
        if not self._cancel_bucket.take():
            raise RateLimited("cancel rate budget exceeded")
        order.state = OrderState.PENDING_CANCEL

    def on_fill(self, coid: str, fill_id: str, cumulative_filled: int) -> None:
        order = self._orders[coid]
        if fill_id in order.seen_fill_ids:
            return  # duplicate delivery -> no-op (redelivery-safe)
        order.seen_fill_ids.add(fill_id)
        if cumulative_filled > order.resting_size:
            raise ReconciliationBreak(
                f"{coid}: fill cumulative {cumulative_filled} exceeds resting {order.resting_size}"
            )
        if order.terminal and order.state != OrderState.FILLED:
            raise ReconciliationBreak(f"{coid}: fill after terminal {order.state}")
        order.filled_qty = cumulative_filled
        if cumulative_filled == order.resting_size:
            self._to_terminal(coid, OrderState.FILLED)  # PENDING_CANCEL -> FILLED is legal
        elif cumulative_filled > 0 and order.state == OrderState.ACKNOWLEDGED:
            order.state = OrderState.PARTIALLY_FILLED

    def on_cancelled(self, coid: str) -> None:
        self._to_terminal(coid, OrderState.CANCELLED)

    def on_rejected(self, coid: str) -> None:
        self._to_terminal(coid, OrderState.REJECTED)

    def _to_terminal(self, coid: str, new_state: OrderState) -> None:
        order = self._orders[coid]
        if order.terminal:
            if order.state == new_state:
                return  # duplicate terminal that agrees -> no-op
            raise ReconciliationBreak(
                f"{coid}: terminal {new_state} contradicts existing {order.state}"
            )
        order.state = new_state
        self._state.release(order.intent.intent_id)  # reconcile in-flight exposure

    # ---- introspection ----------------------------------------------------
    def open_orders(self) -> list[OrderRecord]:
        return [o for o in self._orders.values() if not o.terminal]
