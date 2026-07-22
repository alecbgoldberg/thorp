"""Price-discovery taking sim: fill model, fee, detection, end-to-end take."""

from datetime import UTC, datetime, timedelta

from thorp.sim.core import (
    BookTick,
    KalshiTick,
    SimConfig,
    kalshi_fee,
    run_game,
    take_yes_fill,
)

BASE = datetime(2026, 7, 22, 22, 0, tzinfo=UTC)


def at(sec: float) -> datetime:
    return BASE + timedelta(seconds=sec)


def test_kalshi_fee_formula() -> None:
    assert kalshi_fee(0.5, 100) == 1.75  # round_up(0.07*100*0.25)


def test_take_yes_fill_walks_ladder() -> None:
    # no_levels: buy-NO bids. YES ask = 1 - price. Best ask = 1-0.60 = 0.40.
    no_levels = [(0.60, 50), (0.59, 100), (0.58, 100)]
    price, filled = take_yes_fill(no_levels, max_size=120)
    # 50 @ 0.40, 70 @ 0.41 -> avg = (50*0.40 + 70*0.41)/120
    assert filled == 120
    assert abs(price - (50 * 0.40 + 70 * 0.41) / 120) < 1e-9


def test_take_yes_fill_capped_by_depth() -> None:
    price, filled = take_yes_fill([(0.60, 10)], max_size=100)
    assert filled == 10 and abs(price - 0.40) < 1e-9


def _books_agree_then_move() -> tuple[list[BookTick], list[KalshiTick], tuple[str, str]]:
    teams = ("HOME", "AWAY")
    books: list[BookTick] = []
    kalshi: list[KalshiTick] = []
    # Phase 1 (0-100s): books agree at P(home)=0.50, Kalshi mid 0.50 (fair).
    for s in range(0, 101, 10):
        books.append(BookTick(at(s), "pinnacle", {"HOME": 0.50, "AWAY": 0.50}))
        books.append(BookTick(at(s), "espn", {"HOME": 0.505, "AWAY": 0.495}))
        # Kalshi asks ~0.51 (no bids at 0.49): fair, no edge.
        kalshi.append(KalshiTick(at(s), {"HOME": 0.50, "AWAY": 0.50},
                                 {"HOME": [(0.49, 500)], "AWAY": [(0.49, 500)]}))
    # Phase 2 (110-400s): books SHARPLY move to P(home)=0.60 together; Kalshi lags at 0.50.
    for s in range(110, 401, 10):
        books.append(BookTick(at(s), "pinnacle", {"HOME": 0.60, "AWAY": 0.40}))
        books.append(BookTick(at(s), "espn", {"HOME": 0.605, "AWAY": 0.395}))
        # Kalshi HOME still cheap: NO bids at 0.49 -> YES ask 0.51, fair 0.60 -> edge.
        mid = 0.51 if s < 250 else 0.60  # Kalshi converges within the markout horizon
        kalshi.append(KalshiTick(at(s), {"HOME": mid, "AWAY": 1 - mid},
                                 {"HOME": [(0.49, 500)], "AWAY": [(0.41, 500)]}))
    return books, kalshi, teams


def test_discovery_gated_take_captures_edge() -> None:
    books, kalshi, teams = _books_agree_then_move()
    cfg = SimConfig(move_window_s=90, move_threshold=0.02, markout_horizon_s=150, cooldown_s=60)
    r = run_game("g", books, kalshi, teams, cfg)
    assert r.n_discovery > 0
    assert len(r.trades) >= 1
    t = r.trades[0]
    assert t.team == "HOME" and t.side == "buy_yes"
    assert t.fill_price < 0.55  # bought cheap
    assert t.entry_edge > 0
    # Kalshi converged to 0.60 by the horizon -> positive markout.
    assert t.markout is not None and t.markout > 0


def test_no_take_when_books_disagree() -> None:
    # Books far apart (dispersion > agree_threshold) -> no clean discovery.
    teams = ("HOME", "AWAY")
    books, kalshi = [], []
    for s in range(0, 401, 10):
        books.append(BookTick(at(s), "pinnacle", {"HOME": 0.60, "AWAY": 0.40}))
        books.append(BookTick(at(s), "espn", {"HOME": 0.40, "AWAY": 0.60}))  # disagree hugely
        kalshi.append(KalshiTick(at(s), {"HOME": 0.50, "AWAY": 0.50},
                                 {"HOME": [(0.49, 500)], "AWAY": [(0.49, 500)]}))
    r = run_game("g", books, kalshi, teams, SimConfig())
    assert len(r.trades) == 0


def test_greedy_mode_takes_without_discovery() -> None:
    teams = ("HOME", "AWAY")
    books = [BookTick(at(s), "pinnacle", {"HOME": 0.60, "AWAY": 0.40}) for s in range(0, 200, 10)]
    kalshi = [KalshiTick(at(s), {"HOME": 0.50, "AWAY": 0.50},
                         {"HOME": [(0.49, 500)], "AWAY": [(0.49, 500)]}) for s in range(0, 200, 10)]
    r = run_game("g", books, kalshi, teams, SimConfig(require_discovery=False))
    assert len(r.trades) >= 1
