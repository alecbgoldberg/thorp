#!/usr/bin/env python
"""Lead/lag study: does a sharp book (Pinnacle) lead Kalshi? (Doc 13 §6)

Runnable study script. Until real capture exists it runs on synthetic data with
a known injected lead, which validates the method (it must recover the lag).
When Kalshi + Pinnacle capture exists, extend ``load_captured_series`` to feed
the real paired series in — the analysis itself does not change.

    uv run python research/lead_lag/study.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from thorp.research.leadlag import LeadLagResult, lead_lag, synthetic_paired_series

# Pre-registered decision bar (Doc 13 §6).
MIN_LEAD_S = 5.0
MIN_CORR = 0.3

OUTPUT_DIR = Path(__file__).parent / "output"


def run_synthetic(step_s: float, true_lag_s: float, n: int, seed: int) -> LeadLagResult:
    sharp, kalshi = synthetic_paired_series(n=n, step_s=step_s, true_lag_s=true_lag_s, seed=seed)
    return lead_lag(sharp, kalshi, step_s=step_s, max_lag_s=max(30.0, true_lag_s * 3))


def load_captured_series() -> tuple[list[float], list[float], float]:
    """Placeholder for the real paired series (Kalshi mid + de-vigged Pinnacle).

    Not implemented until the Recorder + odds capture have gathered data. When
    they have: resample both onto a common grid (``leadlag.resample_last``),
    de-vig Pinnacle (``leadlag.devig_multiplicative`` or the FairValueEngine's
    Shin method), and return ``(sharp_prob, kalshi_prob, step_s)``.
    """
    raise NotImplementedError(
        "no captured data yet — run the Recorder + `python -m thorp.odds` first, "
        "then wire this to the journaled Kalshi snapshots and Pinnacle quotes."
    )


def write_report(result: LeadLagResult, source: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    verdict = result.verdict(MIN_LEAD_S, MIN_CORR)

    payload = {
        "generated_at": stamp,
        "source": source,
        "bar": {"min_lead_s": MIN_LEAD_S, "min_corr": MIN_CORR},
        "verdict": verdict,
        "result": asdict(result),
    }
    (OUTPUT_DIR / f"lead_lag_{stamp}.json").write_text(json.dumps(payload, indent=2))

    lines = [
        f"# Lead/Lag Study — {stamp}",
        "",
        f"- Source: **{source}**",
        f"- Best lag: **{result.best_lag_s:+.1f}s** "
        f"({'sharp leads Kalshi' if result.sharp_leads else 'no sharp lead'})",
        f"- Peak correlation: **{result.peak_corr:.3f}**  (n={result.n}, grid={result.step_s}s)",
        f"- Pre-registered bar: lead ≥ {MIN_LEAD_S}s and corr ≥ {MIN_CORR}",
        f"- **Verdict: {verdict}**",
        "",
        "| lag (s) | corr |",
        "|--------:|-----:|",
        *[f"| {lag:+.0f} | {corr:.3f} |" for lag, corr in result.lag_table],
    ]
    report = OUTPUT_DIR / f"lead_lag_{stamp}.md"
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captured", action="store_true", help="use captured data once it exists")
    parser.add_argument("--step-s", type=float, default=2.0, help="resample grid step (s)")
    parser.add_argument("--true-lag-s", type=float, default=8.0, help="synthetic injected lead")
    parser.add_argument("--n", type=int, default=600, help="synthetic sample count")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    if args.captured:
        sharp, kalshi, step_s = load_captured_series()
        result = lead_lag(sharp, kalshi, step_s=step_s, max_lag_s=60.0)
        source = "captured (Kalshi + Pinnacle)"
    else:
        result = run_synthetic(args.step_s, args.true_lag_s, args.n, args.seed)
        source = f"synthetic (injected lead {args.true_lag_s:.0f}s)"

    report = write_report(result, source)
    verdict = result.verdict(MIN_LEAD_S, MIN_CORR)
    print(f"source        : {source}")
    print(f"best lag       : {result.best_lag_s:+.1f}s  (peak corr {result.peak_corr:.3f})")
    print(f"sharp leads    : {result.sharp_leads}")
    print(f"verdict        : {verdict}  (bar: lead>={MIN_LEAD_S}s, corr>={MIN_CORR})")
    print(f"report written : {report}")


if __name__ == "__main__":
    main()
