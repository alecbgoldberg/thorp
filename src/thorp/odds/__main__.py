"""Odds capture entrypoint: ``python -m thorp.odds --config config/odds.toml``."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

from thorp.common.clock import CaptureClock
from thorp.common.logging_setup import configure_logging
from thorp.common.secrets import load_env_file
from thorp.odds.capture import OddsCapture
from thorp.odds.config import OddsConfig
from thorp.odds.provider import build_provider
from thorp.recorder.journal import JournalSet


async def _amain(cfg: OddsConfig) -> None:
    import logging

    logger = logging.getLogger("thorp.odds")
    load_env_file(cfg.secrets_file)
    api_key = os.environ.get(cfg.api_key_env)
    if not api_key:
        sys.exit(
            f"no odds API key: set {cfg.api_key_env} in {cfg.secrets_file} "
            f"(see secrets/README.md) for provider {cfg.provider!r}"
        )

    clock = CaptureClock()
    journals = JournalSet(cfg.data_dir, clock, cfg.fsync_interval_s)
    provider = build_provider(cfg, api_key)
    capture = OddsCapture(cfg, provider, clock, journals)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, capture.stop)

    try:
        await capture.run()
    finally:
        journals.close()
        await provider.aclose()
        logger.info("odds capture stopped; journals closed")


def main() -> None:
    parser = argparse.ArgumentParser("thorp-odds", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/odds.toml"))
    args = parser.parse_args()
    configure_logging()
    if not args.config.exists():
        sys.exit(
            f"config not found: {args.config} — copy config/odds.example.toml "
            "to config/odds.toml and edit"
        )
    asyncio.run(_amain(OddsConfig.load(args.config)))


if __name__ == "__main__":
    main()
