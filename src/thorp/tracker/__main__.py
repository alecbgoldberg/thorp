"""MLB moneyline lead/lag tracker entrypoint.

    python -m thorp.tracker --config config/tracker.toml
    python -m thorp.tracker --once     # discover, one sample round, analyze, exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from thorp.common.clock import CaptureClock
from thorp.common.logging_setup import configure_logging
from thorp.common.secrets import load_env_file
from thorp.odds.oddspapi import OddsPapiProvider
from thorp.recorder.kalshi.rest import KalshiRestClient
from thorp.tracker.budget import OddsBudget
from thorp.tracker.config import TrackerConfig
from thorp.tracker.kalshi_mlb import KalshiMlbClient
from thorp.tracker.store import ObservationStore
from thorp.tracker.tracker import Tracker

logger = logging.getLogger("thorp.tracker")


async def _amain(cfg: TrackerConfig, once: bool) -> None:
    load_env_file(cfg.secrets_file)
    api_key = os.environ.get(cfg.api_key_env)
    if not api_key:
        sys.exit(
            f"no OddsPapi key: set {cfg.api_key_env} in {cfg.secrets_file} "
            "(see secrets/README.md)"
        )

    clock = CaptureClock()
    rest = KalshiRestClient(cfg.kalshi_rest_url)  # market data is unauthenticated
    kalshi = KalshiMlbClient(rest, cfg.kalshi_series)
    odds = OddsPapiProvider(api_key=api_key)
    budget = OddsBudget(cfg.data_dir / "odds_budget.json", cfg.monthly_odds_budget)
    store = ObservationStore(cfg.data_dir)
    tracker = Tracker(cfg, kalshi, odds, budget, store, clock)

    logger.info(
        "OddsPapi budget: %d/%d remaining this month",
        budget.remaining(),
        cfg.monthly_odds_budget,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, tracker.stop)

    try:
        if once:
            await tracker.discover()
            await tracker.sample_kalshi()
            await tracker.sample_pinnacle()
            tracker.analyze()
        else:
            await tracker.run()
    finally:
        await rest.aclose()
        await odds.aclose()
        logger.info("tracker stopped")


def main() -> None:
    parser = argparse.ArgumentParser("thorp-tracker", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/tracker.toml"))
    parser.add_argument("--once", action="store_true", help="one round then exit")
    args = parser.parse_args()
    configure_logging()
    cfg = TrackerConfig.load(args.config) if args.config.exists() else TrackerConfig()
    if not args.config.exists():
        logger.info("no config at %s — using defaults", args.config)
    asyncio.run(_amain(cfg, args.once))


if __name__ == "__main__":
    main()
