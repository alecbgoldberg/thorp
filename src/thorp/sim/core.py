"""Price-discovery taking simulation (Doc 16).

The strategy the operator described: monitor multiple books; when they **agree**
and then one **moves sharply**, treat that as price discovery, and **take** on
Kalshi if Kalshi hasn't followed (it's stale) — capturing the edge before Kalshi
converges, and avoiding being picked off the other way.

This module is pure/testable: it runs a prepared per-game timeline of book and
Kalshi ticks and returns the trades + P&L. P&L is measured two ways:
- **entry edge**: (blended fair - fill price) - fee, the theoretical edge at the
  moment of taking (assumes the blended book fair is "true");
- **markout**: (Kalshi mid at t+horizon - fill price) - fee, i.e. did Kalshi
  actually converge toward the book fair after we took? This is the honest
  did-it-work number, needing no settlement outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

Level = tuple[float, float]  # (price_dollars, size)


@dataclass(frozen=True)
class SimConfig:
    agree_threshold: float = 0.015  # books "agree" if their spread < this (prob)
    move_threshold: float = 0.02  # a "sharp move" in blended fair over the window
    move_window_s: float = 90.0  # look-back window for detecting the move
    edge_margin: float = 0.005  # required edge beyond fee to take (prob = dollars)
    max_take_size: int = 200  # cap contracts per take
    cooldown_s: float = 60.0  # min seconds between takes on one game
    markout_horizon_s: float = 300.0  # measure Kalshi convergence this far out
    require_discovery: bool = True  # gate takes on a discovery event (vs any edge)


@dataclass(frozen=True)
class BookTick:
    ts: datetime
    venue: str
    fair: dict[str, float]  # team -> de-vigged P(team wins)


@dataclass(frozen=True)
class KalshiTick:
    ts: datetime
    # team -> (mid, no_levels) ; no_levels are resting buy-NO orders (YES asks = 1-price)
    mid: dict[str, float | None]
    no_levels: dict[str, list[Level]]


@dataclass(frozen=True)
class Trade:
    ts: datetime
    team: str
    side: str  # "buy_yes"
    size: int
    fill_price: float
    fee: float
    fair: float
    entry_edge: float  # (fair - fill) - fee/size, per contract
    markout: float | None = None  # (kalshi_mid@+H - fill) - fee/size, per contract


@dataclass
class GameSimResult:
    game_key: str
    trades: list[Trade] = field(default_factory=list)
    n_discovery: int = 0
    n_evaluations: int = 0

    @property
    def entry_edge_total(self) -> float:
        return sum(t.entry_edge * t.size for t in self.trades)

    @property
    def markout_total(self) -> float:
        return sum((t.markout or 0.0) * t.size for t in self.trades)

    @property
    def markout_hit_rate(self) -> float | None:
        marked = [t for t in self.trades if t.markout is not None]
        if not marked:
            return None
        return sum(1 for t in marked if (t.markout or 0.0) > 0) / len(marked)


def kalshi_fee(price: float, size: int) -> float:
    """Kalshi taker fee ~ round_up(0.07 * C * P * (1-P)) dollars (Doc 1 §1.1)."""
    raw = Decimal("0.07") * size * Decimal(str(price)) * (Decimal(1) - Decimal(str(price)))
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def take_yes_fill(no_levels: list[Level], max_size: int) -> tuple[float, int]:
    """Simulate buying YES by lifting resting buy-NO orders (YES ask = 1 - price).

    Walks the ladder best-first, returns (size-weighted avg fill price, filled).
    """
    asks: list[Level] = sorted(((1.0 - p, s) for p, s in no_levels), key=lambda lv: lv[0])
    filled = 0
    notional = 0.0
    for ask_price, size in asks:
        take = min(int(size), max_size - filled)
        if take <= 0:
            break
        filled += take
        notional += ask_price * take
    if filled == 0:
        return 0.0, 0
    return notional / filled, filled


def _consensus(fair_by_book: dict[str, dict[str, float]], team: str) -> tuple[float | None, float]:
    """(mean fair for team across books, dispersion = max-min)."""
    vals = [fb[team] for fb in fair_by_book.values() if team in fb]
    if not vals:
        return None, 0.0
    return sum(vals) / len(vals), (max(vals) - min(vals))


def run_game(
    game_key: str,
    book_ticks: list[BookTick],
    kalshi_ticks: list[KalshiTick],
    teams: tuple[str, str],
    cfg: SimConfig,
) -> GameSimResult:
    result = GameSimResult(game_key=game_key)
    home = teams[0]
    # Merge into one timeline; book ticks update fair, kalshi ticks are eval points.
    events: list[tuple[datetime, str, object]] = [(t.ts, "book", t) for t in book_ticks]
    events += [(t.ts, "kalshi", t) for t in kalshi_ticks]
    events.sort(key=lambda e: e[0])

    # Kalshi mid index per team for markout lookups.
    mid_index: dict[str, list[tuple[float, float]]] = {t: [] for t in teams}
    for kt in kalshi_ticks:
        for team in teams:
            m = kt.mid.get(team)
            if m is not None:
                mid_index[team].append((kt.ts.timestamp(), m))

    fair_by_book: dict[str, dict[str, float]] = {}
    consensus_hist: list[tuple[float, float]] = []  # (epoch, consensus P(home))
    last_kalshi: KalshiTick | None = None
    last_take_epoch = -1e18

    for ts, kind, payload in events:
        if kind == "book":
            assert isinstance(payload, BookTick)
            fair_by_book[payload.venue] = payload.fair
            ch, _ = _consensus(fair_by_book, home)
            if ch is not None:
                consensus_hist.append((ts.timestamp(), ch))
            continue

        # kalshi tick: an evaluation point
        assert isinstance(payload, KalshiTick)
        last_kalshi = payload
        result.n_evaluations += 1
        ch, dispersion = _consensus(fair_by_book, home)
        if ch is None:
            continue
        discovery = _is_discovery(consensus_hist, ts.timestamp(), dispersion, cfg)
        if discovery:
            result.n_discovery += 1
        if cfg.require_discovery and not discovery:
            continue
        if ts.timestamp() - last_take_epoch < cfg.cooldown_s:
            continue
        trade = _try_take(game_key, ts, teams, fair_by_book, last_kalshi, mid_index, cfg)
        if trade is not None:
            result.trades.append(trade)
            last_take_epoch = ts.timestamp()
    return result


def _is_discovery(
    consensus_hist: list[tuple[float, float]], now: float, dispersion: float, cfg: SimConfig
) -> bool:
    if dispersion >= cfg.agree_threshold:
        return False  # books not in agreement -> not a clean discovery
    prior = [v for (e, v) in consensus_hist if e <= now - cfg.move_window_s]
    if not prior or not consensus_hist:
        return False
    return abs(consensus_hist[-1][1] - prior[-1]) >= cfg.move_threshold


def _try_take(
    game_key: str,
    ts: datetime,
    teams: tuple[str, str],
    fair_by_book: dict[str, dict[str, float]],
    kalshi: KalshiTick,
    mid_index: dict[str, list[tuple[float, float]]],
    cfg: SimConfig,
) -> Trade | None:
    best: Trade | None = None
    for team in teams:
        fair, _ = _consensus(fair_by_book, team)
        levels = kalshi.no_levels.get(team) or []
        if fair is None or not levels:
            continue
        fill, filled = take_yes_fill(levels, cfg.max_take_size)
        if filled == 0:
            continue
        gross_edge = fair - fill
        if gross_edge <= cfg.edge_margin:
            continue
        fee = kalshi_fee(fill, filled)
        entry_edge = gross_edge - fee / filled
        if entry_edge <= 0:
            continue
        markout = _markout(mid_index.get(team, []), ts.timestamp(), fill, fee, filled, cfg)
        trade = Trade(
            ts=ts, team=team, side="buy_yes", size=filled, fill_price=fill, fee=fee,
            fair=fair, entry_edge=entry_edge, markout=markout,
        )
        if best is None or trade.entry_edge > best.entry_edge:
            best = trade
    return best


def _markout(
    mids: list[tuple[float, float]],
    entry: float,
    fill: float,
    fee: float,
    size: int,
    cfg: SimConfig,
) -> float | None:
    target = entry + cfg.markout_horizon_s
    later = [m for (e, m) in mids if e >= target]
    if not later:
        return None
    return (later[0] - fill) - fee / size
