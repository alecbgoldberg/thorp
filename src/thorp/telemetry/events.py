"""Engine telemetry schema (Doc 3 §3.8 event log, §3.9 status file).

Two artifacts the Trading Engine writes and the monitor (and Control CLI) read —
never by reaching into engine memory, always via these files, so a wedged
engine can still be observed and killed (Doc 3 §3.9):

- **Event log**: append-only JSONL, one ``*Event`` per line, the full history
  of intents / risk decisions / order transitions / fills / halts. This is also
  the BACKTEST replay input (Doc 3 §3.8), so it must be complete and ordered.
- **Status file**: a single ``EngineStatus`` JSON snapshot, rewritten
  atomically (temp + rename, Doc 3 §5) each cycle — the authoritative "current
  state" (open orders, positions, current mids). The monitor derives
  mark-to-mid P&L from it.

The engine that emits these does not exist yet (Phase 2, Doc 7 Week 6); this
schema is fixed now so the monitor is built against it and the sim lights it up
unchanged. Prices/quantities are ``Decimal`` dollars, serialized as exact JSON
strings.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["buy_yes", "sell_yes"]


class RunMode(StrEnum):
    BACKTEST = "BACKTEST"
    SIMULATION = "SIMULATION"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"


class OrderState(StrEnum):
    # The revised OMS machine (Doc 3 §3.6).
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=True)


class FillModelTags(_Frozen):
    """The fill-model-assumptions vector on a shadow fill (Doc 3 §4).

    Present in SIMULATION so the monitor and the sim-vs-live divergence report
    can attribute a gap to a specific assumption. ``None`` for real fills.
    """

    queue_position: str  # e.g. "back_of_queue"
    modeled_latency_ms: int
    print_allocation: str  # e.g. "exclusive" | "shared_denied"
    self_excluded: bool


# --------------------------------------------------------------- event stream


class OrderIntentEvent(_Frozen):
    event_type: Literal["order_intent"] = "order_intent"
    seq: int
    ts: datetime
    intent_id: str
    market_key: str
    side: Side
    price: Decimal
    size: int
    reason: str
    correlated_group: str


class RiskDecisionEvent(_Frozen):
    event_type: Literal["risk_decision"] = "risk_decision"
    seq: int
    ts: datetime
    intent_id: str
    decision: Literal["approved", "modified", "rejected"]
    market_key: str
    original_size: int
    approved_size: int  # 0 for rejected
    reason: str  # human-readable why (fade, hard cap, staleness, ...)


class OrderStateEvent(_Frozen):
    event_type: Literal["order_state"] = "order_state"
    seq: int
    ts: datetime
    order_id: str
    market_key: str
    state: OrderState
    filled_qty: int = 0
    resting_qty: int = 0


class FillEvent(_Frozen):
    event_type: Literal["fill"] = "fill"
    seq: int
    ts: datetime
    fill_id: str
    order_id: str
    market_key: str
    correlated_group: str
    side: Side
    price: Decimal
    size: int
    fee: Decimal
    liquidity: Literal["maker", "taker"]
    fill_model: FillModelTags | None = None  # set in SIMULATION only


class HaltEvent(_Frozen):
    event_type: Literal["halt"] = "halt"
    seq: int
    ts: datetime
    halted: bool
    reason: str


Event = Annotated[
    OrderIntentEvent | RiskDecisionEvent | OrderStateEvent | FillEvent | HaltEvent,
    Field(discriminator="event_type"),
]


# ---------------------------------------------------------------- status file


class MarketMark(_Frozen):
    market_key: str
    bid: Decimal | None
    ask: Decimal | None
    mid: Decimal | None  # engine-reported; monitor falls back to (bid+ask)/2
    last_trade: Decimal | None = None


class OpenOrder(_Frozen):
    order_id: str
    market_key: str
    correlated_group: str
    side: Side
    price: Decimal
    size: int
    filled: int
    state: OrderState
    submitted_at: datetime
    reason: str = ""
    fill_model: FillModelTags | None = None


class PositionMark(_Frozen):
    market_key: str
    correlated_group: str
    net_contracts: int  # signed: + long YES, - short YES
    avg_entry: Decimal  # dollars; 0 when flat
    realized_pnl: Decimal


class GroupExposure(_Frozen):
    """Per-correlated-group exposure vs the fading caps (Doc 2 §5)."""

    correlated_group: str
    exposure: Decimal  # includes in-flight reservations (Doc 3 §3.5)
    soft_cap: Decimal
    hard_cap: Decimal


class EngineStatus(_Frozen):
    schema_version: int = 1
    mode: RunMode
    updated_at: datetime
    started_at: datetime
    halted: bool = False
    halt_reason: str | None = None
    last_event_seq: int = 0
    markets: list[MarketMark] = Field(default_factory=list)
    open_orders: list[OpenOrder] = Field(default_factory=list)
    positions: list[PositionMark] = Field(default_factory=list)
    groups: list[GroupExposure] = Field(default_factory=list)
    fees_paid: Decimal = Decimal(0)

    def to_json(self) -> str:
        return self.model_dump_json()
