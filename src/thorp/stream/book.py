"""In-memory Kalshi order book maintained from WS snapshot + deltas.

Real-time alternative to 5s REST snapshots: apply each ``orderbook_delta`` as it
arrives (sub-second) and keep the book current, so the engine sees the market
move as it happens rather than at a poll cadence. Pure/testable — the WS client
(``kalshi_ws.py``) feeds it; this just maintains state.

Schema (verified live): deltas carry ``side`` (yes/no), ``price_dollars``, and a
signed ``delta_fp`` size change; a snapshot carries ``yes_dollars_fp`` /
``no_dollars_fp`` level arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

Level = tuple[Decimal, Decimal]  # (price_dollars, size)


def _d(v: object) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except ArithmeticError:
        return None


@dataclass
class LiveBook:
    # price (dollars) -> resting size; yes = buy-YES bids, no = buy-NO bids.
    yes: dict[Decimal, Decimal] = field(default_factory=dict)
    no: dict[Decimal, Decimal] = field(default_factory=dict)

    def apply_snapshot(self, yes_levels: object, no_levels: object) -> None:
        self.yes = _levels_to_dict(yes_levels)
        self.no = _levels_to_dict(no_levels)

    def apply_delta(self, side: str, price: object, delta: object) -> None:
        p, d = _d(price), _d(delta)
        if p is None or d is None:
            return
        book = self.yes if side == "yes" else self.no
        book[p] = book.get(p, Decimal(0)) + d
        if book[p] <= 0:
            book.pop(p, None)

    def bbo(self) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        best_yes = max(self.yes, default=None)  # best buy-YES bid
        best_no = max(self.no, default=None)  # best buy-NO bid
        bid = best_yes
        ask = (Decimal(1) - best_no) if best_no is not None else None
        if bid is not None and ask is not None:
            mid: Decimal | None = (bid + ask) / 2
        else:
            mid = bid if bid is not None else ask
        return bid, ask, mid

    def ladder(self, top: int = 10) -> tuple[list[Level], list[Level]]:
        yes = sorted(self.yes.items(), key=lambda lv: lv[0], reverse=True)[:top]
        no = sorted(self.no.items(), key=lambda lv: lv[0], reverse=True)[:top]
        return yes, no


def _levels_to_dict(levels: object) -> dict[Decimal, Decimal]:
    out: dict[Decimal, Decimal] = {}
    if isinstance(levels, list):
        for row in levels:
            p, s = _d(row[0]), _d(row[1])
            if p is not None and s is not None and s > 0:
                out[p] = s
    return out
