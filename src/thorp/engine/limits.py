"""Risk limits (Doc 4 control catalog). Defaults are the CANARY tier."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskLimits:
    # Per-order (Doc 4 §1)
    max_order_size: int = 1  # canary: single contract
    price_band_vs_fair: Decimal = Decimal("0.15")
    price_band_vs_last: Decimal = Decimal("0.10")
    hard_price_min: Decimal = Decimal("0.02")
    hard_price_max: Decimal = Decimal("0.98")
    fat_finger_notional: Decimal = Decimal("50")

    # Per correlated group (Doc 4 §2 / Doc 2 §5)
    hard_cap: Decimal = Decimal("50")  # canary group cap
    soft_cap: Decimal = Decimal("25")  # fade trigger
    max_open_orders_group: int = 4

    # Portfolio (Doc 4 §3)
    max_gross_exposure: Decimal = Decimal("100")

    # P&L (Doc 4 §5)
    intraday_max_loss: Decimal = Decimal("20")
    drawdown_from_high: Decimal = Decimal("10")  # 50% of intraday max loss
    per_strategy_max_loss: Decimal = Decimal("10")

    # Rate (Doc 4 §4) — enforced in the OMS
    max_orders_per_sec: float = 2.0
    max_cancels_per_sec: float = 5.0

    @classmethod
    def tier1(cls, balance: Decimal) -> RiskLimits:
        hard = min(Decimal("150"), (balance * Decimal("0.15")))
        return cls(
            max_order_size=10,
            fat_finger_notional=Decimal("150"),
            hard_cap=hard,
            soft_cap=hard / 2,
            max_open_orders_group=6,
            max_gross_exposure=balance * Decimal("0.40"),
            intraday_max_loss=Decimal("75"),
            drawdown_from_high=Decimal("37.5"),
            per_strategy_max_loss=Decimal("30"),
        )
