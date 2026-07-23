"""Watchdog / dead-man switch (Doc 4 §8) — separate process, deliberately simple.

Polls the engine's heartbeat; if it goes stale (>10s), fires the kill action.
The kill is **verified**: retried with backoff, then re-checked that nothing is
left working; if it can't confirm, it escalates loudly (the Opus gap-2 fix), not
"I sent the request" == "it worked".

**RULE #1 (sim/prod separation):** in SIMULATION the kill is `SimKillAction` —
it writes a halt flag the engine obeys and does **no** venue call, because no
live orders exist and sim must never touch a live venue. A live cancel-all kill
belongs to a future `LiveKillAction` bound to a real venue; it does not exist
yet, on purpose.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from thorp.engine.heartbeat import HeartbeatReader

logger = logging.getLogger("thorp.watchdog")


class KillAction(Protocol):
    async def __call__(self) -> int:
        """Perform the kill; return the number of orders still working after it
        (0 = confirmed flat)."""
        ...


class SimKillAction:
    """Sim kill: write the halt flag, do NOTHING to any venue (rule #1)."""

    def __init__(self, halt_flag: Path) -> None:
        self._halt_flag = halt_flag

    async def __call__(self) -> int:
        self._halt_flag.parent.mkdir(parents=True, exist_ok=True)
        self._halt_flag.write_text(f"watchdog dead-man @ {datetime.now(UTC).isoformat()}")
        logger.error("DEAD-MAN SWITCH FIRED (SIMULATION): halt flag written, no venue call")
        return 0  # no live orders exist in sim


class Watchdog:
    def __init__(
        self,
        reader: HeartbeatReader,
        kill: KillAction,
        stale_threshold_s: float = 10.0,
        poll_s: float = 2.0,
        max_retries: int = 3,
        retry_backoff_s: float = 1.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._kill = kill
        self._stale = stale_threshold_s
        self._poll = poll_s
        self._max_retries = max_retries
        self._backoff = retry_backoff_s
        self._clock = clock
        self._fired = False
        self._seen_alive = False  # armed only after we've seen a healthy heartbeat
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def check_once(self) -> bool:
        """One poll. Returns True if the kill fired this tick."""
        age = self._reader.age_s(self._clock())
        if age <= self._stale:
            self._seen_alive = True  # engine is alive -> now armed
            self._fired = False  # healthy again -> re-arm
            return False
        if not self._seen_alive:
            return False  # startup grace: never fired before the engine came up
        if self._fired:
            return False  # already fired; don't spam
        self._fired = True
        logger.error("heartbeat stale %.1fs (> %.0fs) — firing dead-man switch", age, self._stale)
        await self._fire()
        return True

    async def _fire(self) -> None:
        for attempt in range(1, self._max_retries + 1):
            remaining = await self._kill()
            if remaining == 0:
                logger.error("dead-man fired; flatten CONFIRMED (0 orders working)")
                return
            logger.error("kill attempt %d left %d orders; retrying", attempt, remaining)
            await asyncio.sleep(attempt * self._backoff)
        logger.critical("DEAD-MAN FIRED BUT COULD NOT CONFIRM FLATTEN — escalate immediately")

    async def run(self) -> None:
        logger.info("watchdog: threshold %.0fs, poll %.0fs", self._stale, self._poll)
        while not self._stop.is_set():
            await self.check_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll)
                break
            except TimeoutError:
                pass
