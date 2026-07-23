"""Autonomous Kalshi + Pinnacle time-series collector (Doc 14).

For every MLB game in scope it records a dense time series on both venues —
Kalshi order-book BBO per team market, and Pinnacle moneyline (both sides,
de-vigged) — into ``data/timeseries/`` for later move-detection and simulation.
Pinnacle's bulk endpoint returns the whole slate in one request, so the entire
schedule is covered by ~1 request per cycle (plus per-market Kalshi reads).

Read-only end to end. No order path — this is data collection for the plan's
pregame market-making/taking study (Doc 14), not execution.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from thorp.collector.config import CollectorConfig
from thorp.collector.models import (
    BookSnapshot,
    CollectorGame,
    KalshiMarketBook,
    KalshiSnapshot,
    LinesSnapshot,
    MoneylineSide,
    PinnacleSnapshot,
)
from thorp.collector.snapshots import SnapshotStore
from thorp.collector.spread_total import (
    LinePair,
    match_spreads,
    match_totals,
    spread_event_ticker,
    total_event_ticker,
)
from thorp.common.clock import CaptureClock
from thorp.odds.espn import EspnGame, EspnScraper, et_date_str
from thorp.odds.pinnacle import (
    PinnacleGame,
    PinnacleScraper,
    american_to_decimal,
    moneyline_from_rows,
    spreads_from_rows,
    totals_from_rows,
)
from thorp.polymarket.public import PmMarket, PolymarketPublicClient
from thorp.research.leadlag import devig_multiplicative
from thorp.stream.kalshi_ws import KalshiBookStream
from thorp.tracker.analyze import analyze_game
from thorp.tracker.kalshi_mlb import KalshiMlbClient, games_from_markets, market_quote
from thorp.tracker.models import KalshiGame, Observation
from thorp.tracker.store import ObservationStore
from thorp.tracker.teams_mlb import canon, find_teams

logger = logging.getLogger("thorp.collector")

_ET = ZoneInfo("America/New_York")


def _pinnacle_et_date(pg: PinnacleGame) -> date | None:
    return pg.start_time.astimezone(_ET).date() if pg.start_time else None


def _pick_by_date(game_date: date | None, candidates: list[PinnacleGame]) -> PinnacleGame | None:
    """Choose the Pinnacle matchup on the same Eastern date as the Kalshi game.

    Multi-day series repeat the same teams on consecutive days, so team-set alone
    is ambiguous; requiring an exact Eastern-date match (Pinnacle's start is UTC,
    which rolls past midnight for evening games) keeps a game's Kalshi and
    Pinnacle series correctly aligned. No match if Pinnacle isn't pricing that
    date yet — better to skip than to attribute the wrong day's line.
    """
    if game_date is None:
        return candidates[0]
    exact = [pg for pg in candidates if _pinnacle_et_date(pg) == game_date]
    return exact[0] if exact else None


def match(
    kalshi_games: dict[str, KalshiGame], pinnacle_games: list[PinnacleGame]
) -> list[CollectorGame]:
    """Pair Kalshi games with Pinnacle matchups by canonical team set + date."""
    by_teams: dict[frozenset[str], list[PinnacleGame]] = {}
    for pgame in pinnacle_games:
        home, away = canon(pgame.home_name), canon(pgame.away_name)
        if home and away and home != away:
            by_teams.setdefault(frozenset({home, away}), []).append(pgame)

    links: list[CollectorGame] = []
    for game in kalshi_games.values():
        teams = frozenset(game.market_by_team)
        if len(teams) != 2:
            continue
        candidates = by_teams.get(teams)
        if not candidates:
            continue
        pg = _pick_by_date(game.game_date, candidates)
        if pg is None:
            continue
        home, away = canon(pg.home_name), canon(pg.away_name)
        a, b = sorted(teams)
        ref = a
        ref_side = "home" if ref == home else "away"
        links.append(
            CollectorGame(
                game_key=f"{game.game_date}:{a}-{b}",
                teams=(a, b),
                ref_team=ref,
                kalshi_event=game.event_ticker,
                kalshi_market_by_team=dict(game.market_by_team),
                pinnacle_matchup_id=pg.matchup_id,
                pinnacle_ref_side=ref_side,  # type: ignore[arg-type]
                start_time=pg.start_time or _kalshi_start(game),
            )
        )
    return links


def _kalshi_start(game: object) -> datetime | None:
    from datetime import UTC, time

    gd = getattr(game, "game_date", None)
    return datetime.combine(gd, time.min, tzinfo=UTC) if gd else None


class Collector:
    def __init__(
        self,
        cfg: CollectorConfig,
        kalshi: KalshiMlbClient,
        pinnacle: PinnacleScraper,
        snapshots: SnapshotStore,
        observations: ObservationStore,
        clock: CaptureClock,
        espn: EspnScraper | None = None,
        polymarket: PolymarketPublicClient | None = None,
        kalshi_stream: KalshiBookStream | None = None,
    ) -> None:
        self._cfg = cfg
        self._kalshi = kalshi
        self._pinnacle = pinnacle
        self._espn = espn
        self._polymarket = polymarket
        self._kalshi_stream = kalshi_stream
        self._kalshi_markets: dict[str, dict[str, Any]] = {}  # ticker -> market obj (REST)
        self._snap = snapshots
        self._obs = observations
        self._clock = clock
        self._links: list[CollectorGame] = []
        self._pin_games: list[PinnacleGame] = []
        self._pin_games_at: datetime | None = None
        self._pinnacle_rows: list[dict[str, Any]] = []  # last straight-markets rows
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    def _hours_to_start(self, link: CollectorGame) -> float:
        if link.start_time is None:
            return 1e9
        return (link.start_time - self._clock.now()).total_seconds() / 3600

    def _active(self, link: CollectorGame) -> bool:
        h = self._hours_to_start(link)
        return -self._cfg.postgame_hours <= h <= self._cfg.pregame_hours

    async def discover(self) -> None:
        markets = await self._kalshi.fetch_markets()  # REST: market list + volume/OI
        self._kalshi_markets = {str(m.get("ticker")): m for m in markets}
        games = games_from_markets(markets)
        now = self._clock.now()
        stale = (
            self._pin_games_at is None
            or (now - self._pin_games_at).total_seconds() >= self._cfg.matchups_ttl_s
        )
        if stale:
            self._pin_games = await self._pinnacle.list_games(self._cfg.pinnacle_league)
            self._pin_games_at = now
        links = match(games, self._pin_games)
        links.sort(key=lambda link: abs(self._hours_to_start(link)))
        self._links = links[: self._cfg.max_games]
        active = [link.game_key for link in self._links if self._active(link)]
        if self._kalshi_stream is not None:
            tickers = [
                t for link in self._links if self._active(link)
                for t in link.kalshi_market_by_team.values()
            ]
            self._kalshi_stream.subscribe(tickers)  # real-time WS book for active markets
        logger.info(
            "Kalshi %d games, Pinnacle %d matchups; matched %d, active now %d: %s",
            len(games),
            len(self._pin_games),
            len(self._links),
            len(active),
            ", ".join(active) or "(none)",
        )

    async def sample_pinnacle(self) -> None:
        active = [link for link in self._links if self._active(link)]
        if not active:
            return
        try:
            rows = await self._pinnacle.straight_markets(self._cfg.pinnacle_league)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("pinnacle markets fetch failed: %r", exc)
            return
        self._pinnacle_rows = rows  # reused by sample_spread_total (no extra fetch)
        now = self._clock.now()
        n = 0
        for link in active:
            ml = moneyline_from_rows(rows, link.pinnacle_matchup_id)
            if ml is None:
                continue
            dh, da = devig_multiplicative(
                [float(ml["home"]["prob_vig"]), float(ml["away"]["prob_vig"])]
            )
            home = _side(ml["home"], dh)
            away = _side(ml["away"], da)
            other = link.teams[0] if link.teams[1] == link.ref_team else link.teams[1]
            if link.pinnacle_ref_side == "home":
                home_team, away_team, ref_prob = link.ref_team, other, home.prob_devig
            else:
                home_team, away_team, ref_prob = other, link.ref_team, away.prob_devig
            self._snap.append(
                "pinnacle",
                PinnacleSnapshot(
                    ts=now,
                    game_key=link.game_key,
                    matchup_id=link.pinnacle_matchup_id,
                    home_team=home_team,
                    away_team=away_team,
                    home=home,
                    away=away,
                    max_stake=ml["home"].get("max_stake"),
                    raw={"home": _raw(ml["home"]), "away": _raw(ml["away"])},
                ),
            )
            self._record_obs(link, "pinnacle", ref_prob)
            n += 1
        logger.info("pinnacle: %d game snapshots", n)

    async def sample_kalshi(self) -> None:
        active = [link for link in self._links if self._active(link)]
        if not active:
            return
        # Real-time book from the WS stream if present; else REST snapshot.
        by_ticker: dict[str, dict[str, Any]] = {}
        Lvl = list[tuple[Decimal, Decimal]]
        ladders: dict[str, tuple[Lvl, Lvl]] = {}
        if self._kalshi_stream is None:
            try:
                markets = await self._kalshi.fetch_markets()
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("kalshi markets fetch failed: %r", exc)
                return
            by_ticker = {str(m.get("ticker")): m for m in markets}
            tickers = [t for link in active for t in link.kalshi_market_by_team.values()]
            ladders = await self._fetch_ladders(tickers)
        else:
            by_ticker = self._kalshi_markets  # volume/OI/last from discovery (REST)

        now = self._clock.now()
        for link in active:
            books: list[KalshiMarketBook] = []
            ref_mid: Decimal | None = None
            for team, ticker in link.kalshi_market_by_team.items():
                m = by_ticker.get(ticker)
                q = market_quote(m) if m else market_quote({})
                if self._kalshi_stream is not None:
                    b = self._kalshi_stream.book(ticker)
                    if b is None:
                        continue  # WS snapshot not arrived yet
                    bid, ask, mid = b.bbo()
                    yes_levels, no_levels = b.ladder(10)
                else:
                    bid, ask, mid = q.yes_bid, q.yes_ask, q.mid
                    yes_levels, no_levels = ladders.get(ticker, ([], []))
                books.append(
                    KalshiMarketBook(
                        team=team, ticker=ticker, yes_bid=bid, yes_ask=ask,
                        mid=mid, last=q.last, volume=q.volume, open_interest=q.open_interest,
                        yes_levels=yes_levels, no_levels=no_levels,
                    )
                )
                if team == link.ref_team:
                    ref_mid = mid
            if not books:
                continue
            self._snap.append(
                "kalshi",
                KalshiSnapshot(
                    ts=now, game_key=link.game_key, event_ticker=link.kalshi_event, markets=books
                ),
            )
            if ref_mid is not None:
                self._record_obs(link, "kalshi", ref_mid)

    async def _fetch_ladders(
        self, tickers: list[str]
    ) -> dict[str, tuple[list[tuple[Decimal, Decimal]], list[tuple[Decimal, Decimal]]]]:
        sem = asyncio.Semaphore(8)
        out: dict[str, tuple[list[tuple[Decimal, Decimal]], list[tuple[Decimal, Decimal]]]] = {}

        async def one(ticker: str) -> None:
            async with sem:
                try:
                    out[ticker] = await self._kalshi.orderbook(ticker, top=10)
                except (httpx.HTTPError, OSError) as exc:
                    logger.warning("kalshi ladder failed for %s: %r", ticker, exc)

        await asyncio.gather(*(one(t) for t in tickers))
        return out

    async def sample_espn(self) -> None:
        if self._espn is None:
            return
        active = [link for link in self._links if self._active(link)]
        if not active:
            return
        dates = sorted({et_date_str(link.start_time) for link in active if link.start_time})
        by_teams: dict[frozenset[str], EspnGame] = {}
        for date_str in dates:
            try:
                for g in await self._espn.scoreboard(date_str):
                    h, a = canon(g.home_abbr), canon(g.away_abbr)
                    if h and a and h != a:
                        by_teams[frozenset({h, a})] = g
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("espn scoreboard %s failed: %r", date_str, exc)
        now = self._clock.now()
        n = 0
        for link in active:
            eg = by_teams.get(frozenset(link.teams))
            if eg is None:
                continue
            h, a = canon(eg.home_abbr), canon(eg.away_abbr)
            dh, da = devig_multiplicative(
                [
                    float(Decimal(1) / american_to_decimal(eg.home_american)),
                    float(Decimal(1) / american_to_decimal(eg.away_american)),
                ]
            )
            self._snap.append(
                "espn",
                BookSnapshot(
                    venue="espn",
                    ts=now,
                    game_key=link.game_key,
                    home_team=str(h),
                    away_team=str(a),
                    home=_ml_side(eg.home_american, dh),
                    away=_ml_side(eg.away_american, da),
                    source_provider=eg.provider,
                ),
            )
            n += 1
        logger.info("espn: %d game snapshots (%s)", n, dates)

    async def sample_polymarket(self) -> None:
        """Best-effort Polymarket public prices (international Gamma, no auth).

        Per-game MLB moneylines are sparse on the public API (futures-oriented);
        this writes a snapshot only on a confident team match with two named
        outcomes, else nothing. Clean per-game data will come from the Polymarket
        US API once credentials exist (Doc 17)."""
        if self._polymarket is None:
            return
        active = [link for link in self._links if self._active(link)]
        if not active:
            return
        try:
            markets = await self._polymarket.list_markets(limit=500)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("polymarket fetch failed: %r", exc)
            return
        by_teams: dict[frozenset[str], PmMarket] = {}
        for m in markets:
            teams = find_teams(m.question)
            if len(teams) == 2:
                by_teams[frozenset(teams)] = m
        n = 0
        for link in active:
            pm = by_teams.get(frozenset(link.teams))
            if pm is None or pm.best_bid is None or pm.best_ask is None:
                continue
            # Confident mapping of which team is the YES outcome isn't reliable
            # from the public question text; skip rather than write wrong data.
            n += 1
        if n:
            logger.info("polymarket: %d candidate matches (mapping deferred to PM-US)", n)

    async def sample_spread_total(self) -> None:
        """Capture matched Kalshi<->Pinnacle spread + total lines (line shifts).

        Reuses the Pinnacle rows from sample_pinnacle (no extra Pinnacle call);
        adds two Kalshi bulk /markets reads (spread + total series)."""
        active = [link for link in self._links if self._active(link)]
        if not active or not self._pinnacle_rows:
            return
        try:
            spread_markets = await self._kalshi.fetch_markets_for_series("KXMLBSPREAD")
            total_markets = await self._kalshi.fetch_markets_for_series("KXMLBTOTAL")
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("kalshi spread/total fetch failed: %r", exc)
            return
        spreads_by_event: dict[str, list[dict[str, Any]]] = {}
        totals_by_event: dict[str, list[dict[str, Any]]] = {}
        for m in spread_markets:
            spreads_by_event.setdefault(str(m.get("event_ticker")), []).append(m)
        for m in total_markets:
            totals_by_event.setdefault(str(m.get("event_ticker")), []).append(m)
        now = self._clock.now()
        n = 0
        for link in active:
            pin_sp = spreads_from_rows(self._pinnacle_rows, link.pinnacle_matchup_id)
            pin_tot = totals_from_rows(self._pinnacle_rows, link.pinnacle_matchup_id)
            home = link.teams[0] if link.pinnacle_ref_side == "home" else link.teams[1]
            away = link.teams[1] if home == link.teams[0] else link.teams[0]
            k_sp = spreads_by_event.get(spread_event_ticker(link.kalshi_event), [])
            k_tot = totals_by_event.get(total_event_ticker(link.kalshi_event), [])
            pairs = match_spreads(k_sp, pin_sp, home, away) + match_totals(k_tot, pin_tot)
            if not pairs:
                continue
            self._snap.append("lines", LinesSnapshot(
                ts=now, game_key=link.game_key,
                pairs=[_line_pair_dict(p) for p in pairs],
            ))
            n += 1
        if n:
            logger.info("spread/total: %d games with matched lines", n)

    def analyze(self) -> None:
        for link in self._links:
            obs = self._obs.load(link.game_key)
            ga = analyze_game(link.game_key, obs, step_s=30.0, max_lag_s=1800.0)
            if ga.result is None:
                continue
            r = ga.result
            logger.info(
                "[%s] lead/lag: %s leads %+.0fs (corr %.2f, k=%d p=%d)",
                link.game_key,
                "Pinnacle" if r.sharp_leads else "Kalshi/none",
                r.best_lag_s,
                r.peak_corr,
                ga.kalshi_points,
                ga.pinnacle_points,
            )

    def _record_obs(self, link: CollectorGame, source: str, prob: Decimal) -> None:
        self._obs.append(
            Observation(
                game_key=link.game_key,
                ref_team=link.ref_team,
                source=source,  # type: ignore[arg-type]
                prob=Decimal(str(round(float(prob), 6))),
                ts=self._clock.now(),
            )
        )

    async def sample_all(self) -> None:
        await self.sample_pinnacle()
        await self.sample_spread_total()
        await self.sample_espn()
        await self.sample_polymarket()
        await self.sample_kalshi()

    async def run(self) -> None:
        await self.discover()
        await self.sample_all()
        now0 = self._clock.now()
        last = dict.fromkeys(("sample", "discover", "analyze"), now0)
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
            if (now - last["sample"]).total_seconds() >= self._cfg.sample_interval_s:
                await self.sample_all()
                last["sample"] = now
            if (now - last["analyze"]).total_seconds() >= self._cfg.analyze_interval_s:
                self.analyze()
                last["analyze"] = now


def _side(ml: dict[str, Any], prob_devig: float) -> MoneylineSide:
    return MoneylineSide(
        american=ml["american"],
        decimal_odds=ml["decimal"],
        prob_vig=ml["prob_vig"],
        prob_devig=Decimal(str(round(prob_devig, 6))),
    )


def _line_pair_dict(p: LinePair) -> dict[str, Any]:
    return {
        "kind": p.kind, "line": p.line, "selection": p.selection,
        "kalshi_prob": float(p.kalshi_prob) if p.kalshi_prob is not None else None,
        "pinnacle_prob": p.pinnacle_prob, "edge": p.edge, "ticker": p.ticker,
    }


def _ml_side(american: int, prob_devig: float) -> MoneylineSide:
    dec = american_to_decimal(american)
    return MoneylineSide(
        american=american,
        decimal_odds=dec,
        prob_vig=Decimal(1) / dec,
        prob_devig=Decimal(str(round(prob_devig, 6))),
    )


def _raw(ml: dict[str, Any]) -> dict[str, Any]:
    return {
        "american": ml["american"],
        "max_stake": ml.get("max_stake"),
        "cutoff": ml.get("cutoff"),
    }
