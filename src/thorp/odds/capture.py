"""Odds capture loop — polls the provider and journals quotes (Doc 13 §5).

Same journal/timestamp discipline as the Recorder (Doc 5): local append-only
JSONL, three-timestamp records, partitioned by ``venue=<provider>``. This is
what gathers the sharp-book (Pinnacle) series the lead/lag study consumes
alongside the Kalshi book the Recorder captures.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta

import httpx

from thorp.common.clock import CaptureClock
from thorp.odds.config import OddsConfig
from thorp.odds.provider import OddsProvider
from thorp.recorder.journal import JournalSet

logger = logging.getLogger("thorp.odds")

DT_QUOTES = "odds"
DT_FIXTURES = "fixtures"


class OddsCapture:
    def __init__(
        self,
        cfg: OddsConfig,
        provider: OddsProvider,
        clock: CaptureClock,
        journals: JournalSet,
    ) -> None:
        self._cfg = cfg
        self._provider = provider
        self._clock = clock
        self._journals = journals
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        logger.info(
            "odds capture: provider=%s bookmakers=%s sports=%s",
            self._provider.name,
            list(self._cfg.bookmakers),
            list(self._cfg.sports),
        )
        while not self._stop.is_set():
            try:
                await self._poll_once()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    # Auth/config problem — retrying won't fix it; make it loud.
                    logger.error(
                        "odds API rejected the key (HTTP %d). Check %s in %s "
                        "(see secrets/README.md). Still retrying in case it's fixed live.",
                        status,
                        self._cfg.api_key_env,
                        self._cfg.secrets_file,
                    )
                else:
                    logger.warning("odds poll HTTP %d: %r — will retry", status, exc)
            except (httpx.HTTPError, OSError) as exc:
                # Transient (timeout, connection refused, DNS, API down) — retry.
                logger.warning("odds poll failed (%r) — API may be down; will retry", exc)
            drift = self._clock.resync()
            if abs(drift) > 0.05:
                logger.warning("clock resync drift %.6fs", drift)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._cfg.poll_interval_s)

    async def _poll_once(self) -> None:
        now = self._clock.now()
        window_end = now + timedelta(hours=self._cfg.fixture_lookahead_hours)
        total_quotes = 0
        fixture_count = 0
        for sport in self._cfg.sports:
            fixtures = await self._provider.list_fixtures(sport, now, window_end)
            fixture_count += len(fixtures)
            for fx in fixtures:
                self._journals.write(self._provider.name, DT_FIXTURES, fx)
                quotes = await self._provider.fetch_quotes(
                    fx.fixture_id, sport, list(self._cfg.bookmakers)
                )
                for quote in quotes:
                    self._journals.write(self._provider.name, DT_QUOTES, quote)
                total_quotes += len(quotes)
                await asyncio.sleep(0.05)  # stay gentle on the free tier
        logger.info("polled %d fixtures, %d quotes", fixture_count, total_quotes)
