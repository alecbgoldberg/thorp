"""Position / P&L / fee accounting (Doc 3 §3.7).

Signed average-cost per market: realized P&L crystallizes when a fill reduces or
flips the position; unrealized marks the open position to the current Kalshi mid.
Fees accumulate separately. Feeds both the RiskState (positions) and the status
file the monitor renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from thorp.engine.types import Side


@dataclass
class Position:
    net: int = 0  # signed: + long YES, - short YES
    avg: Decimal = Decimal(0)  # avg entry price (dollars) of the open position
    realized: Decimal = Decimal(0)


@dataclass
class PositionAccounting:
    positions: dict[str, Position] = field(default_factory=dict)
    group_by_market: dict[str, str] = field(default_factory=dict)
    fees_paid: Decimal = Decimal(0)

    def apply_fill(
        self, market: str, group: str, side: Side, price: Decimal, size: int, fee: Decimal
    ) -> None:
        self.group_by_market[market] = group
        self.fees_paid += fee
        pos = self.positions.setdefault(market, Position())
        q = size if side == "buy_yes" else -size
        if pos.net == 0 or (pos.net > 0) == (q > 0):
            total = abs(pos.net) + abs(q)
            pos.avg = (pos.avg * abs(pos.net) + price * abs(q)) / total
            pos.net += q
            return
        closing = min(abs(q), abs(pos.net))
        sign = 1 if pos.net > 0 else -1
        pos.realized += Decimal(closing) * (price - pos.avg) * sign
        remainder = abs(q) - abs(pos.net)
        if remainder > 0:  # flipped through zero
            pos.net = (1 if q > 0 else -1) * remainder
            pos.avg = price
        else:
            pos.net += q
            if pos.net == 0:
                pos.avg = Decimal(0)

    def realized(self) -> Decimal:
        return sum((p.realized for p in self.positions.values()), Decimal(0))

    def unrealized(self, mids: dict[str, Decimal | None]) -> Decimal:
        total = Decimal(0)
        for market, pos in self.positions.items():
            mid = mids.get(market)
            if mid is not None and pos.net != 0:
                total += Decimal(pos.net) * (mid - pos.avg)
        return total

    def group_exposure(self, group: str) -> Decimal:
        total = Decimal(0)
        for market, pos in self.positions.items():
            if self.group_by_market.get(market) == group and pos.net != 0:
                risk = pos.avg if pos.net > 0 else (Decimal(1) - pos.avg)
                total += abs(pos.net) * risk
        return total
