"""ShadowVenue — SIMULATION fills against the live Kalshi book (Doc 3 §4).

No orders are sent to Kalshi. A taking order is filled by walking the live
order-book ladder up to its limit price, size-capped, with the real Kalshi taker
fee. This is the pessimistic-by-default taker path; the resting-quote /
latency-model refinements (Doc 3 §4) are deliberately not yet modeled here — a
first, honest taker sim that the risk/OMS path runs through end to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from thorp.engine.types import ApprovedIntent, ModifiedIntent, Side

Level = tuple[Decimal, Decimal]  # (price_dollars, size)


@dataclass(frozen=True)
class ShadowFill:
    fill_id: str
    market: str
    side: Side
    price: Decimal  # size-weighted avg fill price
    size: int
    fee: Decimal


def kalshi_fee(price: Decimal, size: int) -> Decimal:
    raw = Decimal("0.07") * size * price * (Decimal(1) - price)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _walk(asks: list[Level], limit: Decimal, max_size: int) -> tuple[Decimal, int]:
    """Consume ascending asks up to ``limit`` price, capped at ``max_size``."""
    filled = 0
    notional = Decimal(0)
    for price, size in sorted(asks, key=lambda lv: lv[0]):
        if price > limit:
            break
        take = min(int(size), max_size - filled)
        if take <= 0:
            break
        filled += take
        notional += price * take
    if filled == 0:
        return Decimal(0), 0
    return (notional / filled), filled


class ShadowVenue:
    def __init__(self) -> None:
        self._fill_seq = 0

    def fill(
        self,
        approved: ApprovedIntent | ModifiedIntent,
        yes_levels: list[Level],
        no_levels: list[Level],
    ) -> ShadowFill | None:
        """Simulate a marketable take. ``yes_levels`` = resting buy-YES bids,
        ``no_levels`` = resting buy-NO bids (a YES ask is 1 - a NO bid price)."""
        intent = approved.intent
        size = approved.approved_size
        if intent.side == "buy_yes":
            asks = [(Decimal(1) - p, s) for p, s in no_levels]  # YES asks
            avg, filled = _walk(asks, intent.price, size)
        else:  # sell_yes -> lift resting buy-YES bids at/above our limit
            bids = sorted(yes_levels, key=lambda lv: lv[0], reverse=True)
            filled = 0
            notional = Decimal(0)
            for price, lvl_size in bids:
                if price < intent.price:
                    break
                take = min(int(lvl_size), size - filled)
                if take <= 0:
                    break
                filled += take
                notional += price * take
            avg = (notional / filled) if filled else Decimal(0)
        if filled == 0:
            return None
        self._fill_seq += 1
        return ShadowFill(
            fill_id=f"shadow-{self._fill_seq}",
            market=intent.market_ticker,
            side=intent.side,
            price=avg,
            size=filled,
            fee=kalshi_fee(avg, filled),
        )
