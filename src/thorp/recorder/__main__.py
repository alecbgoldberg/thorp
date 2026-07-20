"""Recorder entrypoint: ``python -m thorp.recorder --config config/recorder.toml``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from thorp.common.clock import CaptureClock
from thorp.recorder.capture import KalshiCapture
from thorp.recorder.config import RecorderConfig
from thorp.recorder.journal import JournalSet
from thorp.recorder.kalshi.auth import KalshiSigner
from thorp.recorder.kalshi.rest import KalshiRestClient

logger = logging.getLogger("thorp.recorder")


def _build_signer(cfg: RecorderConfig) -> KalshiSigner | None:
    key_id = os.environ.get(cfg.api_key_id_env)
    key_path = os.environ.get(cfg.private_key_path_env)
    if not key_id or not key_path:
        return None
    return KalshiSigner.from_pem_file(key_id, Path(key_path))


async def _amain(cfg: RecorderConfig) -> None:
    clock = CaptureClock()
    journals = JournalSet(cfg.data_dir, clock, cfg.fsync_interval_s)
    signer = _build_signer(cfg)
    if signer is None:
        logger.warning(
            "no Kalshi credentials found (env %s / %s) — running unauthenticated; "
            "the WS connection will be rejected if the venue requires auth. "
            "See docs/08-open-questions.md §2 for account setup.",
            cfg.api_key_id_env,
            cfg.private_key_path_env,
        )
    rest = KalshiRestClient(cfg.rest_url, signer)
    capture = KalshiCapture(cfg, clock, journals, rest, signer)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, capture.stop)

    try:
        await capture.run()
    finally:
        journals.close()
        await rest.aclose()
        logger.info("recorder stopped; journals closed")


def main() -> None:
    parser = argparse.ArgumentParser("thorp-recorder", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/recorder.toml"))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.config.exists():
        sys.exit(
            f"config not found: {args.config} — copy config/recorder.example.toml "
            "to config/recorder.toml and edit"
        )
    asyncio.run(_amain(RecorderConfig.load(args.config)))


if __name__ == "__main__":
    main()
