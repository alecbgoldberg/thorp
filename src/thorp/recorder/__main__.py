"""Recorder entrypoint: ``python -m thorp.recorder --config config/recorder.toml``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from thorp.common.clock import CaptureClock
from thorp.common.logging_setup import configure_logging
from thorp.common.secrets import CredentialScope, load_env_file, resolve_credential
from thorp.recorder.capture import KalshiCapture
from thorp.recorder.config import RecorderConfig
from thorp.recorder.journal import JournalSet
from thorp.recorder.kalshi.auth import KalshiSigner
from thorp.recorder.kalshi.rest import KalshiRestClient

logger = logging.getLogger("thorp.recorder")


def _build_signer(cfg: RecorderConfig) -> KalshiSigner | None:
    # Load secrets/kalshi.env if present (real env vars win). The Recorder only
    # ever uses the READ-ONLY scope — it cannot place orders even if asked to.
    loaded = load_env_file(cfg.secrets_file)
    if loaded:
        logger.info("loaded %d value(s) from %s", loaded, cfg.secrets_file)
    cred = resolve_credential(CredentialScope.READ_ONLY)
    if cred is None:
        return None
    logger.info("using read-only Kalshi credential from %s", cred.source)
    return KalshiSigner.from_pem_bytes(cred.api_key_id, cred.private_key_pem, cred.source)


async def _amain(cfg: RecorderConfig) -> None:
    clock = CaptureClock()
    journals = JournalSet(cfg.data_dir, clock, cfg.fsync_interval_s)
    signer = _build_signer(cfg)
    if signer is None:
        logger.warning(
            "no read-only Kalshi credential found (checked %s and the environment) "
            "— running unauthenticated; the WS connection will be rejected if the "
            "venue requires auth. See secrets/README.md for setup.",
            cfg.secrets_file,
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
    configure_logging()
    if not args.config.exists():
        sys.exit(
            f"config not found: {args.config} — copy config/recorder.example.toml "
            "to config/recorder.toml and edit"
        )
    asyncio.run(_amain(RecorderConfig.load(args.config)))


if __name__ == "__main__":
    main()
