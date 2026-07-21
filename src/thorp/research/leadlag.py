"""Lead/lag analysis: does a sharp book (Pinnacle) move *before* Kalshi?

The Doc 13 §6 method, in pure Python (no numpy dependency — the series are
short and this stays trivially installable and fully testable):

1. Resample each irregular time series (sharp implied prob, Kalshi mid) onto a
   common fixed grid with last-value-carried-forward.
2. Cross-correlate at a range of integer lags. Convention: a **positive** lag
   means the *sharp* series leads Kalshi (sharp at ``t - lag`` predicts Kalshi
   at ``t``).
3. Report the lag at peak correlation and whether it clears the pre-registered
   bar (sharp leads by ≥ a floor number of seconds — so it isn't an HFT race we
   would lose — Doc 13 §6).

De-vigging a real Pinnacle line to a fair probability happens before this
(``devig_multiplicative`` is a minimal helper; Shin/Power live in the
FairValueEngine per Doc 1 §2.3). The synthetic generator lets the method be
validated end to end — it must recover a known injected lag — before any real
data exists.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


def pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation; 0.0 for degenerate (constant) input."""
    n = len(x)
    if n < 3 or n != len(y):
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((xi - mx) ** 2 for xi in x)
    syy = sum((yi - my) ** 2 for yi in y)
    if sxx <= 0 or syy <= 0:
        return 0.0
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=True))
    return sxy / math.sqrt(sxx * syy)


def resample_last(
    times: list[float], values: list[float], t0: float, t1: float, step_s: float
) -> list[float]:
    """Last-value-carried-forward resample onto ``[t0, t1)`` at ``step_s``.

    ``times`` must be sorted ascending. Grid points before the first observation
    take the first value (best available prior estimate).
    """
    if not times:
        return []
    grid_n = max(0, math.floor((t1 - t0) / step_s))
    out: list[float] = []
    idx = 0
    last = values[0]
    for k in range(grid_n):
        t = t0 + k * step_s
        while idx < len(times) and times[idx] <= t:
            last = values[idx]
            idx += 1
        out.append(last)
    return out


def cross_correlation(
    sharp: list[float], kalshi: list[float], max_lag_steps: int
) -> list[tuple[int, float]]:
    """Correlation of ``kalshi[t]`` with ``sharp[t - lag]`` for each integer lag
    in ``[-max_lag_steps, +max_lag_steps]``. Positive lag ⇒ sharp leads."""
    n = min(len(sharp), len(kalshi))
    sharp, kalshi = sharp[:n], kalshi[:n]
    table: list[tuple[int, float]] = []
    for lag in range(-max_lag_steps, max_lag_steps + 1):
        if lag >= 0:
            a, b = kalshi[lag:], sharp[: n - lag]
        else:
            a, b = kalshi[: n + lag], sharp[-lag:]
        if len(a) >= 3:
            table.append((lag, pearson(a, b)))
    return table


@dataclass(frozen=True)
class LeadLagResult:
    step_s: float
    best_lag_s: float  # > 0 ⇒ sharp leads Kalshi
    peak_corr: float
    sharp_leads: bool
    n: int
    lag_table: list[tuple[float, float]]  # (lag_seconds, corr)

    def verdict(self, min_lead_s: float, min_corr: float) -> str:
        if self.sharp_leads and self.best_lag_s >= min_lead_s and self.peak_corr >= min_corr:
            return "PASS"
        return "FAIL"


def lead_lag(
    sharp: list[float], kalshi: list[float], step_s: float, max_lag_s: float
) -> LeadLagResult:
    max_steps = max(1, round(max_lag_s / step_s))
    table = cross_correlation(sharp, kalshi, max_steps)
    if not table:
        return LeadLagResult(step_s, 0.0, 0.0, False, len(sharp), [])
    best_lag, peak = max(table, key=lambda lc: lc[1])
    return LeadLagResult(
        step_s=step_s,
        best_lag_s=best_lag * step_s,
        peak_corr=peak,
        sharp_leads=best_lag > 0,
        n=min(len(sharp), len(kalshi)),
        lag_table=[(lag * step_s, corr) for lag, corr in table],
    )


def devig_multiplicative(implied_probs: list[float]) -> list[float]:
    """Normalize vig-inclusive implied probabilities to sum to 1 (Doc 1 §2.3,
    the naive method; Shin/Power are preferred downstream but this suffices to
    turn a two-way moneyline into a probability for the lead/lag series)."""
    total = sum(implied_probs)
    if total <= 0:
        return implied_probs
    return [p / total for p in implied_probs]


def synthetic_paired_series(
    n: int, step_s: float, true_lag_s: float, noise: float = 0.01, seed: int = 0
) -> tuple[list[float], list[float]]:
    """A sharp probability random walk and a Kalshi series that lags it by
    ``true_lag_s`` (plus noise). Used to validate the method recovers the lag."""
    rng = random.Random(seed)
    lag_steps = round(true_lag_s / step_s)
    sharp: list[float] = []
    p = 0.5
    for _ in range(n):
        p = min(0.98, max(0.02, p + rng.gauss(0, 0.01)))
        sharp.append(p)
    kalshi = [
        min(0.99, max(0.01, sharp[max(0, i - lag_steps)] + rng.gauss(0, noise)))
        for i in range(n)
    ]
    return sharp, kalshi
