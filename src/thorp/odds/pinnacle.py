"""Pinnacle odds via its own backend JSON API (Doc 14).

Pinnacle's website frontend calls ``guest.api.arcadia.pinnacle.com`` with a
public frontend ``X-API-Key`` (embedded in their JS bundle, not an account
secret). We use the same endpoints — far more robust and *lighter on their
servers* than rendering the React site with Selenium/BeautifulSoup:

- ``GET /0.1/leagues/{league}/matchups`` — games. Real games have ``parentId``
  null and two ``participants`` with ``alignment`` home/away and team ``name``,
  so home/away is given explicitly (unlike OddsPapi).
- ``GET /0.1/leagues/{league}/markets/straight`` — **one request returns every
  game's markets** (moneyline/spread/total). Moneyline prices are **American
  odds** tagged by ``designation`` home/away, plus a ``limits`` max stake.

Baseball = sport 3, MLB = league 246 (verified live 2026-07-21).

Respectful by default: a configurable minimum interval between requests (our own
rate limiting), a browser User-Agent, and 429/5xx retries — polite, and it keeps
our IP from getting blocked. ToS considerations are the operator's call and
noted in docs/14; this module just implements the access.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx

from thorp.common.records import JsonDict
from thorp.odds.types import Fixture, OddsQuoteRecord

logger = logging.getLogger("thorp.pinnacle")

# Public frontend key from pinnacle.com's JS bundle (not an account credential).
# If it rotates, re-extract it from the site's JS.
DEFAULT_API_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
DEFAULT_BASE_URL = "https://guest.api.arcadia.pinnacle.com/0.1"
MLB_LEAGUE = "246"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

Alignment = Literal["home", "away"]


def american_to_decimal(american: float) -> Decimal:
    """American odds -> decimal odds (payout multiple incl. stake)."""
    a = Decimal(str(american))
    if a >= 0:
        return Decimal(1) + a / 100
    return Decimal(1) + Decimal(100) / (-a)


@dataclass(frozen=True)
class PinnacleGame:
    matchup_id: int
    start_time: datetime | None
    home_name: str
    away_name: str


@dataclass
class PinnacleScraper:
    api_key: str = DEFAULT_API_KEY
    base_url: str = DEFAULT_BASE_URL
    min_interval_s: float = 1.0  # our own rate limit between requests
    timeout_s: float = 20.0
    transport: httpx.AsyncBaseTransport | None = None
    _client: httpx.AsyncClient = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _last_request: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_s,
            transport=self.transport,
            headers={
                "X-API-Key": self.api_key,
                "User-Agent": _BROWSER_UA,
                "Referer": "https://www.pinnacle.com/",
                "Origin": "https://www.pinnacle.com",
                "Accept": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "pinnacle"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> Any:
        async with self._lock:  # serialize + space out requests (rate limit)
            wait = self.min_interval_s - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            for attempt in (1, 2, 3):
                response = await self._client.get(path)
                if response.status_code in (429, 500, 502, 503) and attempt < 3:
                    logger.warning("pinnacle %s -> %d; backing off", path, response.status_code)
                    await asyncio.sleep(attempt * 2.0)
                    continue
                self._last_request = time.monotonic()
                response.raise_for_status()
                return response.json()
            self._last_request = time.monotonic()
            raise RuntimeError("unreachable")  # pragma: no cover

    # -------------------------------------------------------------- bulk API

    async def list_games(self, league: str = MLB_LEAGUE) -> list[PinnacleGame]:
        return _parse_games(await self._get(f"/leagues/{league}/matchups"))

    async def straight_markets(self, league: str = MLB_LEAGUE) -> list[JsonDict]:
        """Every game's straight markets in one request (moneyline/spread/total)."""
        rows = await self._get(f"/leagues/{league}/markets/straight")
        return list(rows) if isinstance(rows, list) else []

    # ---------------------------------------------------- OddsProvider compat

    async def list_fixtures(self, sport: str, start: datetime, end: datetime) -> list[Fixture]:
        games = await self.list_games(sport or MLB_LEAGUE)
        return [
            Fixture(
                provider="pinnacle",
                fixture_id=str(g.matchup_id),
                sport=sport or MLB_LEAGUE,
                tournament="MLB",
                start_time=g.start_time,
                p1_name=g.away_name,
                p2_name=g.home_name,
                has_odds=True,
                pinnacle_id=str(g.matchup_id),
            )
            for g in games
        ]

    async def fetch_quotes(
        self, fixture_id: str, sport: str, bookmakers: list[str]
    ) -> list[OddsQuoteRecord]:
        rows = await self._get(f"/matchups/{fixture_id}/markets/related/straight")
        ml = moneyline_from_rows(list(rows), int(fixture_id))
        if ml is None:
            return []
        fetched = datetime.now(UTC)
        quotes: list[OddsQuoteRecord] = []
        for side in ("home", "away"):
            dec = ml[side]["decimal"]
            quotes.append(
                OddsQuoteRecord(
                    provider="pinnacle",
                    bookmaker="pinnacle",
                    fixture_id=fixture_id,
                    sport=sport or MLB_LEAGUE,
                    market="moneyline",
                    outcome=side,
                    decimal_odds=dec,
                    implied_prob=Decimal(1) / dec,
                    fetched_ts=fetched,
                    raw=ml[side],
                )
            )
        return quotes


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_games(matchups: Any) -> list[PinnacleGame]:
    games: list[PinnacleGame] = []
    for m in matchups if isinstance(matchups, list) else []:
        if m.get("parentId") is not None:
            continue
        parts = m.get("participants")
        if not isinstance(parts, list) or len(parts) != 2:
            continue
        by_align = {p.get("alignment"): p.get("name") for p in parts}
        if by_align.keys() != {"home", "away"}:
            continue
        mid = m.get("id")
        if mid is None:
            continue
        games.append(
            PinnacleGame(
                matchup_id=int(mid),
                start_time=_parse_ts(m.get("startTime")),
                home_name=str(by_align["home"]),
                away_name=str(by_align["away"]),
            )
        )
    return games


def moneyline_from_rows(rows: list[JsonDict], matchup_id: int) -> dict[str, dict[str, Any]] | None:
    """Extract the full-game moneyline for a matchup from straight-market rows.

    Returns ``{"home": {...}, "away": {...}}`` with american/decimal/prob and the
    max stake, or None if no full-game moneyline is present (suspended/absent).
    """
    for row in rows:
        if row.get("matchupId") != matchup_id or row.get("type") != "moneyline":
            continue
        if row.get("period") != 0:
            continue
        prices = row.get("prices") or []
        by_side: dict[str, dict[str, Any]] = {}
        for pr in prices:
            side = pr.get("designation")
            price = pr.get("price")
            if side in ("home", "away") and price is not None:
                dec = american_to_decimal(price)
                by_side[side] = {
                    "american": int(price),
                    "decimal": dec,
                    "prob_vig": Decimal(1) / dec,
                    "max_stake": _max_stake(row),
                    "cutoff": row.get("cutoffAt"),
                }
        if by_side.keys() == {"home", "away"}:
            return by_side
    return None


def _max_stake(row: JsonDict) -> int | None:
    for lim in row.get("limits") or []:
        if lim.get("type") == "maxRiskStake":
            return int(lim.get("amount", 0))
    return None
