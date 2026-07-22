"""Run the price-discovery taking sim over collected data.

    python -m thorp.sim                 # all captured games
    python -m thorp.sim --greedy        # take on any edge, not just discovery events
"""

from __future__ import annotations

import argparse
from pathlib import Path

from thorp.sim.core import SimConfig, run_game
from thorp.sim.loader import list_games, load_game


def main() -> None:
    parser = argparse.ArgumentParser("thorp-sim", description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--greedy", action="store_true",
                        help="take on any edge (not just books-agree-then-move events)")
    parser.add_argument("--markout-horizon-s", type=float, default=300.0)
    parser.add_argument("--edge-margin", type=float, default=0.005)
    args = parser.parse_args()

    cfg = SimConfig(
        require_discovery=not args.greedy,
        markout_horizon_s=args.markout_horizon_s,
        edge_margin=args.edge_margin,
    )
    games = list_games(args.data_dir)
    if not games:
        print("no captured games under", args.data_dir / "timeseries",
              "- run the collector first")
        return

    print(f"{'game':26} {'evals':>6} {'disc':>5} {'takes':>6} "
          f"{'entry_edge$':>12} {'markout$':>10} {'hit%':>6}")
    print("-" * 78)
    tot_edge = tot_mark = 0.0
    tot_takes = 0
    marked_hits = marked_n = 0
    for gk in games:
        book_ticks, kalshi_ticks, teams = load_game(args.data_dir, gk)
        if teams is None or not kalshi_ticks:
            continue
        r = run_game(gk, book_ticks, kalshi_ticks, teams, cfg)
        hr = r.markout_hit_rate
        print(f"{gk:26} {r.n_evaluations:>6} {r.n_discovery:>5} {len(r.trades):>6} "
              f"{r.entry_edge_total:>12.2f} {r.markout_total:>10.2f} "
              f"{('%.0f' % (hr*100)) if hr is not None else '  -':>6}")
        tot_edge += r.entry_edge_total
        tot_mark += r.markout_total
        tot_takes += len(r.trades)
        for t in r.trades:
            if t.markout is not None:
                marked_n += 1
                marked_hits += 1 if t.markout > 0 else 0
    print("-" * 78)
    hit = f"{marked_hits/marked_n*100:.0f}" if marked_n else "-"
    print(f"{'TOTAL':26} {'':>6} {'':>5} {tot_takes:>6} "
          f"{tot_edge:>12.2f} {tot_mark:>10.2f} {hit:>6}")
    print(f"\nmode: {'greedy (any edge)' if args.greedy else 'discovery-gated'} · "
          f"markout horizon {cfg.markout_horizon_s:.0f}s · "
          f"entry_edge = theoretical edge at fill; markout = Kalshi convergence P&L")


if __name__ == "__main__":
    main()
