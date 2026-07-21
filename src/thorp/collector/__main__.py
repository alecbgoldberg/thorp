"""Collector entrypoint.

    python -m thorp.collector --config config/collector.toml
    python -m thorp.collector --once     # one discover/sample/analyze round
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from thorp.collector.collector import Collector
from thorp.collector.config import CollectorConfig
from thorp.collector.snapshots import SnapshotStore
from thorp.common.clock import CaptureClock
from thorp.common.logging_setup import configure_logging
from thorp.odds.pinnacle import PinnacleScraper
from thorp.recorder.kalshi.rest import KalshiRestClient
from thorp.tracker.kalshi_mlb import KalshiMlbClient
from thorp.tracker.store import ObservationStore

logger = logging.getLogger("thorp.collector")


async def _amain(cfg: CollectorConfig, once: bool) -> None:
    clock = CaptureClock()
    rest = KalshiRestClient(cfg.kalshi_rest_url)  # market data is unauthenticated
    kalshi = KalshiMlbClient(rest, cfg.kalshi_series)
    pinnacle = PinnacleScraper(min_interval_s=cfg.pinnacle_min_interval_s)
    snapshots = SnapshotStore(cfg.data_dir)
    observations = ObservationStore(cfg.data_dir)
    collector = Collector(cfg, kalshi, pinnacle, snapshots, observations, clock)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, collector.stop)

    try:
        if once:
            await collector.discover()
            await collector.sample_pinnacle()
            await collector.sample_kalshi()
            collector.analyze()
        else:
            await collector.run()
    finally:
        await rest.aclose()
        await pinnacle.aclose()
        logger.info("collector stopped")


def main() -> None:
    parser = argparse.ArgumentParser("thorp-collector", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/collector.toml"))
    parser.add_argument("--once", action="store_true", help="one round then exit")
    args = parser.parse_args()
    configure_logging()
    cfg = CollectorConfig.load(args.config) if args.config.exists() else CollectorConfig()
    if not args.config.exists():
        logger.info("no config at %s — using defaults", args.config)
    asyncio.run(_amain(cfg, args.once))


if __name__ == "__main__":
    main()
