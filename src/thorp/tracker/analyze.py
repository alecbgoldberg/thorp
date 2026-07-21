"""Per-game lead/lag from stored observations (Doc 13 §6).

Splits a game's observations into the Kalshi and Pinnacle probability series,
resamples both onto a common grid, and runs the tested ``leadlag`` method.
Positive lag ⇒ Pinnacle (sharp) leads Kalshi.
"""

from __future__ import annotations

from dataclasses import dataclass

from thorp.research.leadlag import LeadLagResult, lead_lag, resample_last
from thorp.tracker.models import Observation


@dataclass(frozen=True)
class GameAnalysis:
    game_key: str
    kalshi_points: int
    pinnacle_points: int
    result: LeadLagResult | None
    note: str


def _series(obs: list[Observation], source: str) -> tuple[list[float], list[float]]:
    pts = sorted(
        ((o.ts.timestamp(), float(o.prob)) for o in obs if o.source == source),
        key=lambda p: p[0],
    )
    return [t for t, _ in pts], [v for _, v in pts]


def analyze_game(
    game_key: str,
    obs: list[Observation],
    step_s: float = 5.0,
    max_lag_s: float = 120.0,
    min_points: int = 8,
) -> GameAnalysis:
    k_t, k_v = _series(obs, "kalshi")
    p_t, p_v = _series(obs, "pinnacle")
    if len(k_t) < min_points or len(p_t) < min_points:
        return GameAnalysis(
            game_key, len(k_t), len(p_t), None,
            f"insufficient data (need >= {min_points} per source; "
            f"have kalshi={len(k_t)}, pinnacle={len(p_t)})",
        )
    t0 = max(min(k_t), min(p_t))
    t1 = min(max(k_t), max(p_t))
    if t1 - t0 < step_s * min_points:
        return GameAnalysis(game_key, len(k_t), len(p_t), None, "overlap window too short")

    kalshi = resample_last(k_t, k_v, t0, t1, step_s)
    pinnacle = resample_last(p_t, p_v, t0, t1, step_s)
    result = lead_lag(pinnacle, kalshi, step_s=step_s, max_lag_s=max_lag_s)
    return GameAnalysis(game_key, len(k_t), len(p_t), result, "ok")
