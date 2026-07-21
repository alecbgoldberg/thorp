"""Autonomous MLB moneyline lead/lag tracker (Doc 13).

Syncs each MLB game's win probability on Kalshi (polled densely — it's free)
with Pinnacle via OddsPapi (polled sparsely — hard-capped by the monthly budget)
and, from the paired series, measures whether the sharp line leads Kalshi.

Read-only end to end: it reads Kalshi market data (no auth, no orders) and
OddsPapi odds. No order path exists in this process.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import httpx

from thorp.common.clock import CaptureClock
from thorp.odds.provider import OddsProvider
from thorp.odds.types import Fixture
from thorp.research.leadlag import devig_multiplicative
from thorp.tracker.analyze import analyze_game
from thorp.tracker.budget import OddsBudget
from thorp.tracker.config import TrackerConfig
from thorp.tracker.kalshi_mlb import KalshiMlbClient
from thorp.tracker.matching import match_games, resolve_ref_prob
from thorp.tracker.models import GameLink, Observation
from thorp.tracker.store import ObservationStore

logger = logging.getLogger("thorp.tracker")


class Tracker:
    def __init__(
        self,
        cfg: TrackerConfig,
        kalshi: KalshiMlbClient,
        odds: OddsProvider,
        budget: OddsBudget,
        store: ObservationStore,
        clock: CaptureClock,
    ) -> None:
        self._cfg = cfg
        self._kalshi = kalshi
        self._odds = odds
        self._budget = budget
        self._store = store
        self._clock = clock
        self._links: list[GameLink] = []
        self._orientation: dict[str, str] = {}  # game_key -> "home"/"away"
        self._latest_kalshi: dict[str, float] = {}  # game_key -> P(ref_team)
        self._fixtures: list[Fixture] = []
        self._fixtures_at: datetime | None = None
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def _refresh_fixtures(self) -> None:
        """Refetch OddsPapi fixtures at most once per TTL (budget-costly)."""
        now = self._clock.now()
        fresh = (
            self._fixtures_at is not None
            and (now - self._fixtures_at).total_seconds() < self._cfg.fixtures_ttl_s
        )
        if fresh:
            return
        if not self._budget.try_spend(1):
            return
        end = now + timedelta(hours=self._cfg.fixture_lookahead_hours)
        self._fixtures = await self._odds.list_fixtures(self._cfg.sport_id, now, end)
        self._fixtures_at = now
        logger.info(
            "OddsPapi: %d baseball fixtures (budget left %d)",
            len(self._fixtures),
            self._budget.remaining(),
        )

    def _hours_to_start(self, link: GameLink) -> float:
        if link.start_time is None:
            return 1e9
        return (link.start_time - self._clock.now()).total_seconds() / 3600

    async def discover(self) -> None:
        games = await self._kalshi.list_games()  # free, always fresh
        await self._refresh_fixtures()
        links = match_games(games, self._fixtures)
        # Focus the budget: games near first pitch first, then those Pinnacle
        # actually prices, then soonest — so the daemon tracks tonight's slate.
        links.sort(
            key=lambda link: (
                not self._in_active_window(link),
                link.oddspapi_pinnacle_id is None,
                abs(self._hours_to_start(link)),
            )
        )
        self._links = links[: self._cfg.max_games]
        logger.info(
            "Kalshi: %d open games; tracking %d: %s",
            len(games),
            len(self._links),
            ", ".join(link.game_key for link in self._links) or "(none)",
        )

    async def sample_kalshi(self) -> None:
        for link in self._links:
            ticker = link.kalshi_market_by_team.get(link.ref_team)
            if not ticker:
                continue
            try:
                prob = await self._kalshi.team_prob(ticker)
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("kalshi prob failed for %s: %r", ticker, exc)
                continue
            if prob is None:
                continue
            self._latest_kalshi[link.game_key] = float(prob)
            self._record(link, "kalshi", float(prob), ticker)

    def _in_active_window(self, link: GameLink) -> bool:
        """Only sample Pinnacle around first pitch, to protect the budget."""
        if link.start_time is None:
            return False
        hours_to_start = self._hours_to_start(link)
        # From `active_window_hours` before first pitch until 1h after it.
        return -1.0 <= hours_to_start <= self._cfg.active_window_hours

    async def sample_pinnacle(self) -> None:
        for link in self._links:
            if not self._in_active_window(link):
                continue
            locked = self._orientation.get(link.game_key)
            if locked is None and link.game_key not in self._latest_kalshi:
                continue  # need a Kalshi anchor to lock orientation — don't spend budget
            if not self._budget.try_spend(1):
                return
            try:
                quotes = await self._odds.fetch_quotes(
                    link.oddspapi_fixture_id, self._cfg.sport_id, [self._cfg.bookmaker]
                )
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("pinnacle fetch failed for %s: %r", link.game_key, exc)
                continue
            probs = {q.outcome: float(q.implied_prob) for q in quotes}
            if "home" not in probs or "away" not in probs:
                logger.info("no pinnacle moneyline for %s", link.game_key)
                continue
            dv = devig_multiplicative([probs["home"], probs["away"]])
            anchor = self._latest_kalshi.get(link.game_key, 0.5)
            ref_prob, orientation = resolve_ref_prob(dv[0], dv[1], anchor, locked)
            if locked is None:
                self._orientation[link.game_key] = orientation
                logger.info(
                    "locked %s orientation: ref_team=%s <- %s",
                    link.game_key,
                    link.ref_team,
                    orientation,
                )
            self._record(link, "pinnacle", ref_prob, f"orient={orientation}")

    def analyze(self) -> None:
        for link in self._links:
            obs = self._store.load(link.game_key)
            ga = analyze_game(
                link.game_key,
                obs,
                step_s=self._cfg.analyze_step_s,
                max_lag_s=self._cfg.analyze_max_lag_s,
            )
            if ga.result is None:
                logger.info("[%s] %s", link.game_key, ga.note)
            else:
                r = ga.result
                logger.info(
                    "[%s] lead/lag: %s leads by %+.0fs (corr %.2f, n=%d, k=%d p=%d)",
                    link.game_key,
                    "Pinnacle" if r.sharp_leads else "Kalshi/none",
                    r.best_lag_s,
                    r.peak_corr,
                    r.n,
                    ga.kalshi_points,
                    ga.pinnacle_points,
                )

    def _record(self, link: GameLink, source: str, prob: float, detail: str) -> None:
        obs = Observation(
            game_key=link.game_key,
            ref_team=link.ref_team,
            source=source,  # type: ignore[arg-type]
            prob=Decimal(str(round(prob, 6))),
            ts=self._clock.now(),
            detail=detail,
        )
        self._store.append(obs)

    async def run(self) -> None:
        """Run forever: (re)discover games, sample Kalshi densely + Pinnacle in
        the active window, analyze periodically. Never exits on an empty slate —
        it just waits and re-discovers, so a daemon started at 3am picks up the
        evening games on its own."""
        await self.discover()
        await self.sample_kalshi()
        await self.sample_pinnacle()

        now0 = self._clock.now()
        last = dict.fromkeys(("kalshi", "oddspapi", "analyze", "discover"), now0)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
                break
            except TimeoutError:
                pass
            now = self._clock.now()
            if (now - last["discover"]).total_seconds() >= self._cfg.discover_interval_s:
                await self.discover()
                last["discover"] = now
            if (now - last["kalshi"]).total_seconds() >= self._cfg.kalshi_interval_s:
                await self.sample_kalshi()
                last["kalshi"] = now
            if (now - last["oddspapi"]).total_seconds() >= self._cfg.oddspapi_interval_s:
                await self.sample_pinnacle()
                last["oddspapi"] = now
            if (now - last["analyze"]).total_seconds() >= self._cfg.analyze_interval_s:
                self.analyze()
                last["analyze"] = now
