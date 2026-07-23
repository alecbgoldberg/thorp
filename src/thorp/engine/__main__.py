"""Live SIMULATION engine entrypoint (no real orders).

    python -m thorp.engine --config config/collector.toml
    python -m thorp.engine --once

Feeds the whole UI: writes the 4-source time series (board tab) and the engine
status/events (trading tab). Pair with `python -m thorp.ui` to watch.
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
from thorp.common.secrets import CredentialScope, load_env_file, resolve_credential
from thorp.engine.live_sim import LiveSimEngine
from thorp.odds.espn import EspnScraper
from thorp.odds.pinnacle import PinnacleScraper
from thorp.polymarket.public import PolymarketPublicClient
from thorp.recorder.kalshi.auth import KalshiSigner
from thorp.recorder.kalshi.rest import KalshiRestClient
from thorp.stream.kalshi_ws import KalshiBookStream
from thorp.tracker.kalshi_mlb import KalshiMlbClient
from thorp.tracker.store import ObservationStore

logger = logging.getLogger("thorp.engine")


def _ws_url(rest_url: str) -> str:
    return rest_url.replace("https://", "wss://").replace("/trade-api/v2", "/trade-api/ws/v2")


async def _amain(cfg: CollectorConfig, once: bool) -> None:
    clock = CaptureClock()
    rest = KalshiRestClient(cfg.kalshi_rest_url)
    pinnacle = PinnacleScraper(min_interval_s=cfg.pinnacle_min_interval_s)
    espn = EspnScraper()
    polymarket = PolymarketPublicClient()

    # Real-time Kalshi book over WebSocket (read-only credential; market data).
    load_env_file(Path("secrets/kalshi.env"))
    cred = resolve_credential(CredentialScope.READ_ONLY)
    signer = KalshiSigner.from_pem_bytes(cred.api_key_id, cred.private_key_pem) if cred else None
    if signer is None:
        logger.warning("no read-only Kalshi credential — WS book stream disabled, using REST")
    stream = KalshiBookStream(_ws_url(cfg.kalshi_rest_url), signer) if signer else None

    collector = Collector(
        cfg, KalshiMlbClient(rest, cfg.kalshi_series), pinnacle,
        SnapshotStore(cfg.data_dir), ObservationStore(cfg.data_dir), clock,
        espn=espn, polymarket=polymarket, kalshi_stream=stream,
    )
    engine = LiveSimEngine(
        collector, cfg.data_dir, clock, cfg.sample_interval_s, cfg.discover_interval_s
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, engine.stop)
    stream_task = asyncio.create_task(stream.run()) if stream else None
    try:
        if once:
            await collector.discover()
            await collector.sample_all()
            engine.trade_cycle()
        else:
            await engine.run()
    finally:
        engine.close()
        if stream is not None:
            stream.stop()
        if stream_task is not None:
            stream_task.cancel()
        await rest.aclose()
        await pinnacle.aclose()
        await espn.aclose()
        await polymarket.aclose()
        logger.info("engine stopped")


def main() -> None:
    parser = argparse.ArgumentParser("thorp-engine", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/collector.toml"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    configure_logging()
    cfg = CollectorConfig.load(args.config) if args.config.exists() else CollectorConfig()
    asyncio.run(_amain(cfg, args.once))


if __name__ == "__main__":
    main()
