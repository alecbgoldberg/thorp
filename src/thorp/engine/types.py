"""Engine domain types (Doc 3 §3.4-3.5)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Side = Literal["buy_yes", "sell_yes"]


@dataclass(frozen=True)
class OrderIntent:
    """A strategy's proposed order. Only ever consumed by ``RiskEngine.check`` —
    no method on this type reaches the OMS (Doc 3 §3.4)."""

    strategy_name: str
    market_ticker: str
    correlated_group: str
    side: Side
    price: Decimal
    size: int
    reason: str
    intent_id: str


def contract_risk(side: Side, price: Decimal) -> Decimal:
    """Max loss per contract in dollars: a YES buy loses ``price`` if it settles
    NO; a YES sell (short) loses ``1 - price`` if it settles YES."""
    return price if side == "buy_yes" else (Decimal(1) - price)


def notional(side: Side, price: Decimal, size: int) -> Decimal:
    """Notional at risk (~exposure) of an order (Doc 4 §2)."""
    return contract_risk(side, price) * size


@dataclass(frozen=True)
class ApprovedIntent:
    intent: OrderIntent
    approved_size: int


@dataclass(frozen=True)
class ModifiedIntent:
    intent: OrderIntent
    approved_size: int  # reduced (fade / cap-room / drawdown), always < intent.size
    reason: str


@dataclass(frozen=True)
class RejectedIntent:
    intent: OrderIntent
    reason: str


RiskDecision = ApprovedIntent | ModifiedIntent | RejectedIntent


def decision_size(decision: RiskDecision) -> int:
    if isinstance(decision, RejectedIntent):
        return 0
    return decision.approved_size
