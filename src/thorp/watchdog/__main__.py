"""Watchdog entrypoint — monitors the live engine's heartbeat (Doc 4 §8).

    python -m thorp.watchdog

Separate process from the engine, on purpose. In SIMULATION its kill writes a
halt flag and makes NO venue call (rule #1); a live cancel-all kill is a future
`LiveKillAction` that does not exist yet.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from thorp.common.logging_setup import configure_logging
from thorp.engine.heartbeat import HeartbeatReader
from thorp.engine.watchdog import SimKillAction, Watchdog

logger = logging.getLogger("thorp.watchdog")


async def _amain(data_dir: Path, threshold: float, poll: float) -> None:
    session = data_dir / "live"
    reader = HeartbeatReader(session / "heartbeat")
    watchdog = Watchdog(reader, SimKillAction(session / "halt.flag"),
                        stale_threshold_s=threshold, poll_s=poll)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, watchdog.stop)
    await watchdog.run()
    logger.info("watchdog stopped")


def main() -> None:
    parser = argparse.ArgumentParser("thorp-watchdog", description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--threshold-s", type=float, default=10.0)
    parser.add_argument("--poll-s", type=float, default=2.0)
    args = parser.parse_args()
    configure_logging()
    asyncio.run(_amain(args.data_dir, args.threshold_s, args.poll_s))


if __name__ == "__main__":
    main()
