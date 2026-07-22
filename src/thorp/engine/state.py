"""RiskState — the authoritative, reconciled view + in-flight reservation ledger.

The Opus review's central finding (Doc 4 §2): exposure derived only from
*filled* positions is blind to approved-but-unfilled orders, letting a batch of
intents each pass the same stale cap check and breach it up to 6x. The fix is
``group_exposure`` = reconciled filled exposure **+ every in-flight
reservation**, and reservations are recorded **synchronously at approval time**
(``RiskEngine.check`` mutates this before returning, before any ``await``).
Reservations are released when an order reaches a terminal state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from thorp.engine.types import OrderIntent, Side, notional


@dataclass(frozen=True)
class MarketPosition:
    net_contracts: int  # signed: + long YES, - short YES
    avg_price: Decimal  # dollars

    def exposure(self) -> Decimal:
        if self.net_contracts == 0:
            return Decimal(0)
        risk = self.avg_price if self.net_contracts > 0 else (Decimal(1) - self.avg_price)
        return abs(self.net_contracts) * risk


@dataclass
class _Reservation:
    group: str
    market: str
    notional: Decimal


@dataclass
class RiskState:
    market_to_group: dict[str, str] = field(default_factory=dict)
    positions: dict[str, MarketPosition] = field(default_factory=dict)
    last_trade: dict[str, Decimal] = field(default_factory=dict)
    fair_value: dict[str, Decimal] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal(0)
    unrealized_pnl: Decimal = Decimal(0)
    session_high_pnl: Decimal = Decimal(0)
    strategy_realized: dict[str, Decimal] = field(default_factory=dict)
    open_orders_by_group: dict[str, int] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str | None = None
    _reservations: dict[str, _Reservation] = field(default_factory=dict)

    # ---- exposure ---------------------------------------------------------
    def market_net(self, market: str) -> int:
        pos = self.positions.get(market)
        return pos.net_contracts if pos else 0

    def _reconciled_group_exposure(self, group: str) -> Decimal:
        total = Decimal(0)
        for market, pos in self.positions.items():
            if self.market_to_group.get(market) == group:
                total += pos.exposure()
        return total

    def group_exposure(self, group: str) -> Decimal:
        """Reconciled filled exposure + all in-flight reservations for the group."""
        total = self._reconciled_group_exposure(group)
        total += sum(
            (r.notional for r in self._reservations.values() if r.group == group),
            Decimal(0),
        )
        return total

    def gross_exposure(self) -> Decimal:
        filled = sum((p.exposure() for p in self.positions.values()), Decimal(0))
        inflight = sum((r.notional for r in self._reservations.values()), Decimal(0))
        return filled + inflight

    # ---- reservations (Doc 3 §3.5) ---------------------------------------
    def reserve(self, intent: OrderIntent, size: int) -> None:
        self._reservations[intent.intent_id] = _Reservation(
            group=intent.correlated_group,
            market=intent.market_ticker,
            notional=notional(intent.side, intent.price, size),
        )
        g = intent.correlated_group
        self.open_orders_by_group[g] = self.open_orders_by_group.get(g, 0) + 1

    def release(self, intent_id: str) -> None:
        res = self._reservations.pop(intent_id, None)
        if res is not None:
            self.open_orders_by_group[res.group] = max(
                0, self.open_orders_by_group.get(res.group, 0) - 1
            )

    def has_reservation(self, intent_id: str) -> bool:
        return intent_id in self._reservations

    # ---- helpers ----------------------------------------------------------
    def is_reducing(self, side: Side, market: str) -> bool:
        net = self.market_net(market)
        if side == "buy_yes":
            return net < 0  # buying YES reduces a short-YES position
        return net > 0  # selling YES reduces a long-YES position

    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl

    def strategy_pnl(self, name: str) -> Decimal:
        return self.strategy_realized.get(name, Decimal(0))

    def open_orders(self, group: str) -> int:
        return self.open_orders_by_group.get(group, 0)

    def halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
