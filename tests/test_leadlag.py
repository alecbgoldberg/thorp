"""Lead/lag analysis: correlation, resampling, and lag recovery (Doc 13 §6)."""

from thorp.research.leadlag import (
    cross_correlation,
    devig_multiplicative,
    lead_lag,
    pearson,
    resample_last,
    synthetic_paired_series,
)


def test_pearson_perfect_and_anti() -> None:
    assert abs(pearson([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-9
    assert abs(pearson([1, 2, 3, 4], [8, 6, 4, 2]) + 1.0) < 1e-9


def test_pearson_degenerate_is_zero() -> None:
    assert pearson([1, 1, 1, 1], [1, 2, 3, 4]) == 0.0
    assert pearson([1, 2], [1, 2]) == 0.0  # too few points


def test_resample_last_carries_forward() -> None:
    times = [0.0, 5.0, 12.0]
    values = [0.4, 0.6, 0.5]
    grid = resample_last(times, values, t0=0.0, t1=15.0, step_s=3.0)
    # grid points 0,3,6,9,12 -> 0.4, 0.4, 0.6, 0.6, 0.5
    assert grid == [0.4, 0.4, 0.6, 0.6, 0.5]


def test_devig_sums_to_one() -> None:
    out = devig_multiplicative([1 / 1.90, 1 / 2.10])
    assert abs(sum(out) - 1.0) < 1e-9
    assert out[0] > out[1]  # shorter price -> higher prob


def test_cross_correlation_recovers_injected_lead() -> None:
    step = 2.0
    sharp, kalshi = synthetic_paired_series(n=800, step_s=step, true_lag_s=8.0, noise=0.005, seed=3)
    table = cross_correlation(sharp, kalshi, max_lag_steps=15)
    best_lag, _ = max(table, key=lambda lc: lc[1])
    # Injected lead was 8s = 4 steps; recovered lag should be positive and near it.
    assert best_lag > 0
    assert abs(best_lag * step - 8.0) <= 2.0


def test_lead_lag_verdict_pass_on_synthetic() -> None:
    sharp, kalshi = synthetic_paired_series(n=800, step_s=2.0, true_lag_s=8.0, noise=0.005, seed=5)
    result = lead_lag(sharp, kalshi, step_s=2.0, max_lag_s=30.0)
    assert result.sharp_leads is True
    assert result.best_lag_s >= 5.0
    assert result.verdict(min_lead_s=5.0, min_corr=0.3) == "PASS"


def test_lead_lag_fails_when_no_lead() -> None:
    # Zero injected lag -> peak at lag 0 -> not "sharp leads" -> FAIL the bar.
    sharp, kalshi = synthetic_paired_series(n=600, step_s=2.0, true_lag_s=0.0, noise=0.004, seed=9)
    result = lead_lag(sharp, kalshi, step_s=2.0, max_lag_s=30.0)
    assert result.verdict(min_lead_s=5.0, min_corr=0.3) == "FAIL"
