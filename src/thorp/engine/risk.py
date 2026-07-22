"""RiskEngine — mandatory pass-through gate (Doc 3 §3.5, Doc 4).

``check`` returns an ``ApprovedIntent | ModifiedIntent | RejectedIntent`` and, for
anything not rejected, **reserves the exposure synchronously** in ``RiskState``
before returning — so a batch of intents evaluated back-to-back (before any
fill) each see the prior ones' reservations and cannot breach the group cap
(the Opus in-flight-race fix, Doc 4 §2). The engine never trusts the strategy to
have applied the fade; it re-derives group exposure and re-checks every time.
"""

from __future__ import annotations

import math
from decimal import Decimal

from thorp.engine.limits import RiskLimits
from thorp.engine.state import RiskState
from thorp.engine.types import (
    ApprovedIntent,
    ModifiedIntent,
    OrderIntent,
    RejectedIntent,
    RiskDecision,
    contract_risk,
    notional,
)


def size_multiplier(exposure: Decimal, soft_cap: Decimal, hard_cap: Decimal) -> float:
    """Linear fade between soft_cap and hard_cap (Doc 2 §5). 1.0 below soft,
    0.0 at/above hard."""
    if hard_cap <= 0:
        return 0.0
    ratio = float(exposure / hard_cap)
    soft_ratio = float(soft_cap / hard_cap)
    if ratio <= soft_ratio:
        return 1.0
    if ratio >= 1.0:
        return 0.0
    return 1.0 - (ratio - soft_ratio) / (1.0 - soft_ratio)


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, intent: OrderIntent, state: RiskState) -> RiskDecision:
        lim = self._limits
        reducing = state.is_reducing(intent.side, intent.market_ticker)

        # --- global halt ---------------------------------------------------
        if state.halted and not reducing:
            return RejectedIntent(intent, f"halted: {state.halt_reason}")

        # --- per-order sanity (Doc 4 §1) ----------------------------------
        if not (lim.hard_price_min <= intent.price <= lim.hard_price_max):
            return RejectedIntent(intent, "price outside hard bound")
        fair = state.fair_value.get(intent.market_ticker)
        if fair is not None and abs(intent.price - fair) > lim.price_band_vs_fair:
            return RejectedIntent(intent, "price too far from fair value")
        last = state.last_trade.get(intent.market_ticker)
        if last is not None and abs(intent.price - last) > lim.price_band_vs_last:
            return RejectedIntent(intent, "price too far from last trade")
        if intent.size <= 0:
            return RejectedIntent(intent, "non-positive size")
        if intent.size > lim.max_order_size:
            return RejectedIntent(intent, "exceeds max order size")
        if notional(intent.side, intent.price, intent.size) > lim.fat_finger_notional:
            return RejectedIntent(intent, "exceeds fat-finger notional cap")

        # --- P&L (Doc 4 §5); reducing orders are always allowed to de-risk -
        if not reducing:
            if state.total_pnl() <= -lim.intraday_max_loss:
                state.halt("intraday max loss")
                return RejectedIntent(intent, "intraday max loss halt")
            if state.strategy_pnl(intent.strategy_name) <= -lim.per_strategy_max_loss:
                return RejectedIntent(intent, "per-strategy loss limit")

        # Reducing orders bypass the accumulation controls (they cut exposure).
        if reducing:
            state.reserve(intent, intent.size)
            return ApprovedIntent(intent, intent.size)

        # --- accumulation controls (increasing orders only) ---------------
        group = intent.correlated_group
        if state.open_orders(group) >= lim.max_open_orders_group:
            return RejectedIntent(intent, "max open orders per group")

        per_contract = contract_risk(intent.side, intent.price)
        if per_contract <= 0:
            return RejectedIntent(intent, "degenerate contract risk")

        exposure = state.group_exposure(group)
        if exposure >= lim.hard_cap:
            return RejectedIntent(intent, "group hard cap reached")

        # Fade (Doc 2 §5): shrink by the multiplier at current exposure.
        mult = size_multiplier(exposure, lim.soft_cap, lim.hard_cap)
        faded = math.floor(intent.size * mult)

        # Hard cap room: never let filled+reserved exceed hard_cap.
        room = lim.hard_cap - exposure
        max_by_group_room = math.floor(room / per_contract)

        # Portfolio gross room (Doc 4 §3).
        gross_room = lim.max_gross_exposure - state.gross_exposure()
        max_by_gross = math.floor(gross_room / per_contract) if gross_room > 0 else 0

        final = min(faded, max_by_group_room, max_by_gross)

        # Drawdown-from-high: halve size (warn, don't halt) (Doc 4 §5).
        if state.session_high_pnl - state.total_pnl() >= lim.drawdown_from_high:
            final = math.floor(final / 2)

        if final <= 0:
            return RejectedIntent(intent, "group cap / fade / gross reduced size to zero")

        state.reserve(intent, final)
        if final < intent.size:
            return ModifiedIntent(intent, final, "faded / capped to fit limits")
        return ApprovedIntent(intent, final)
