"""RiskEngine: one negative test per control + fade + the in-flight-race property.

Doc 6 §2: for each bound, construct an intent that violates exactly it and assert
the engine rejects — "if the strategy did this, the engine refuses it."
"""

from decimal import Decimal

from thorp.engine.limits import RiskLimits
from thorp.engine.risk import RiskEngine, size_multiplier
from thorp.engine.state import MarketPosition, RiskState
from thorp.engine.types import (
    ApprovedIntent,
    ModifiedIntent,
    OrderIntent,
    RejectedIntent,
    Side,
)

# Permissive base so each test isolates one control.
PERMISSIVE = RiskLimits(
    max_order_size=10_000, price_band_vs_fair=Decimal("1"), price_band_vs_last=Decimal("1"),
    hard_price_min=Decimal("0.001"), hard_price_max=Decimal("0.999"),
    fat_finger_notional=Decimal("1e9"), hard_cap=Decimal("1e9"), soft_cap=Decimal("1e9"),
    max_open_orders_group=10_000, max_gross_exposure=Decimal("1e9"),
    intraday_max_loss=Decimal("1e9"), drawdown_from_high=Decimal("1e9"),
    per_strategy_max_loss=Decimal("1e9"),
)

_ids = iter(range(1, 10**9))


def intent(price="0.50", size=1, side: Side = "buy_yes", group="G", market="M",
           strat="s1", reason="r") -> OrderIntent:
    return OrderIntent(strat, market, group, side, Decimal(price), size, reason, f"i{next(_ids)}")


def state(**kw) -> RiskState:
    s = RiskState()
    s.market_to_group["M"] = "G"
    s.market_to_group["M2"] = "G"
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ------------------------------------------------------- per-order controls
def test_reject_price_outside_hard_bound() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "hard_price_max": Decimal("0.98")}))
    d = eng.check(intent(price="0.99"), state())
    assert isinstance(d, RejectedIntent) and "hard bound" in d.reason


def test_reject_price_far_from_fair() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "price_band_vs_fair": Decimal("0.15")}))
    s = state(fair_value={"M": Decimal("0.50")})
    assert isinstance(eng.check(intent(price="0.80"), s), RejectedIntent)


def test_reject_price_far_from_last() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "price_band_vs_last": Decimal("0.10")}))
    s = state(last_trade={"M": Decimal("0.50")})
    assert isinstance(eng.check(intent(price="0.65"), s), RejectedIntent)


def test_reject_max_order_size() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "max_order_size": 1}))
    assert isinstance(eng.check(intent(size=2), state()), RejectedIntent)


def test_reject_fat_finger_notional() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "fat_finger_notional": Decimal("50")}))
    # 200 contracts * $0.50 = $100 > $50
    assert isinstance(eng.check(intent(price="0.50", size=200), state()), RejectedIntent)


# ------------------------------------------------------------ P&L controls
def test_reject_per_strategy_loss_limit() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "per_strategy_max_loss": Decimal("10")}))
    s = state(strategy_realized={"s1": Decimal("-10")})
    assert isinstance(eng.check(intent(), s), RejectedIntent)


def test_intraday_max_loss_halts_and_rejects() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "intraday_max_loss": Decimal("20")}))
    s = state(realized_pnl=Decimal("-20"))
    assert isinstance(eng.check(intent(), s), RejectedIntent)
    assert s.halted  # subsequent increasing orders blocked


# ---------------------------------------------------------- group controls
def test_reject_max_open_orders_per_group() -> None:
    eng = RiskEngine(RiskLimits(**{**PERMISSIVE.__dict__, "max_open_orders_group": 2}))
    s = state(open_orders_by_group={"G": 2})
    assert isinstance(eng.check(intent(), s), RejectedIntent)


def test_reject_group_hard_cap() -> None:
    lim = RiskLimits(**{**PERMISSIVE.__dict__, "hard_cap": Decimal("50"),
                        "soft_cap": Decimal("50")})
    eng = RiskEngine(lim)
    pos = MarketPosition(net_contracts=100, avg_price=Decimal("0.50"))
    s = state(positions={"M": pos})
    # group already at $50 exposure -> any increasing order rejected
    assert isinstance(eng.check(intent(market="M2"), s), RejectedIntent)


def test_reject_max_gross_exposure() -> None:
    lim = RiskLimits(**{**PERMISSIVE.__dict__, "max_gross_exposure": Decimal("10")})
    eng = RiskEngine(lim)
    s = state(positions={"M": MarketPosition(net_contracts=20, avg_price=Decimal("0.50"))})
    assert isinstance(eng.check(intent(market="M2", price="0.50", size=1), s), RejectedIntent)


# ------------------------------------------------------------------- fade
def test_size_multiplier_linear_fade() -> None:
    assert size_multiplier(Decimal("20"), Decimal("25"), Decimal("50")) == 1.0  # below soft
    assert size_multiplier(Decimal("50"), Decimal("25"), Decimal("50")) == 0.0  # at hard
    assert abs(size_multiplier(Decimal("30"), Decimal("25"), Decimal("50")) - 0.8) < 1e-9


def test_fade_returns_modified_intent() -> None:
    lim = RiskLimits(**{**PERMISSIVE.__dict__, "hard_cap": Decimal("50"),
                        "soft_cap": Decimal("25"), "max_order_size": 100})
    eng = RiskEngine(lim)
    # group at $30 exposure (between soft 25 and hard 50) -> multiplier 0.8
    s = state(positions={"M": MarketPosition(net_contracts=60, avg_price=Decimal("0.50"))})
    d = eng.check(intent(market="M2", price="0.50", size=5), s)
    assert isinstance(d, ModifiedIntent)
    assert d.approved_size == 4  # floor(5 * 0.8)


# ----------------------------------------------- reducing orders bypass caps
def test_reducing_order_allowed_past_hard_cap() -> None:
    lim = RiskLimits(**{**PERMISSIVE.__dict__, "hard_cap": Decimal("50"),
                        "soft_cap": Decimal("50")})
    eng = RiskEngine(lim)
    # long 100 YES @ 0.50 -> exposure $50 (at cap); a SELL reduces -> allowed
    s = state(positions={"M": MarketPosition(net_contracts=100, avg_price=Decimal("0.50"))})
    d = eng.check(intent(market="M", side="sell_yes", price="0.50", size=1), s)
    assert isinstance(d, ApprovedIntent)


# ------------------- THE in-flight-order race (Doc 6 §3, most important test)
def test_batch_of_intents_cannot_breach_group_cap() -> None:
    """A batch of intents against one group, evaluated before any fill, must never
    push group_exposure past hard_cap — the exact Opus-found 6x-breach shape."""
    lim = RiskLimits(**{**PERMISSIVE.__dict__, "hard_cap": Decimal("150"),
                        "soft_cap": Decimal("150"), "max_order_size": 10_000,
                        "fat_finger_notional": Decimal("1e9")})
    eng = RiskEngine(lim)
    s = state()
    approved = 0
    # 6 intents each worth $150 (300 @ $0.50) against a $150 cap.
    for _ in range(6):
        d = eng.check(intent(price="0.50", size=300), s)
        if not isinstance(d, RejectedIntent):
            approved += 1
        assert s.group_exposure("G") <= lim.hard_cap  # invariant holds after EVERY check
    assert approved == 1  # only the first fits; the rest see its reservation


def test_many_small_intents_fill_cap_exactly_no_more() -> None:
    lim = RiskLimits(**{**PERMISSIVE.__dict__, "hard_cap": Decimal("150"),
                        "soft_cap": Decimal("150"), "max_order_size": 10_000,
                        "fat_finger_notional": Decimal("1e9")})
    eng = RiskEngine(lim)
    s = state()
    approved = 0
    for _ in range(10):  # each $30 (60 @ $0.50); 5 fit into $150
        d = eng.check(intent(price="0.50", size=60), s)
        if not isinstance(d, RejectedIntent):
            approved += 1
        assert s.group_exposure("G") <= lim.hard_cap
    assert approved == 5
