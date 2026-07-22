"""ESPN hidden odds API — a free, unauthenticated second book source (Doc 16).

ESPN's public scoreboard API serves a sportsbook's moneylines (currently
DraftKings) for the whole slate in one request, no key, no geoblock:

    GET site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD

This gives us a recreational-book price (DK) to pair with Pinnacle's sharp line
without scraping DK directly (which is Akamai-walled, Doc 15 §2). ESPN updates
less often than Pinnacle, so it's a confirming/slower source — useful for the
"books agree, one moves" price-discovery signal, not a fast leader.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger("thorp.espn")

DEFAULT_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class EspnGame:
    away_abbr: str
    home_abbr: str
    start_time: datetime | None
    provider: str
    home_american: int
    away_american: int


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _american(side: Any) -> int | None:
    """Extract an American moneyline from an ESPN ``moneyline.{home,away}`` node,
    preferring the current line over the closing/opening one."""
    if not isinstance(side, dict):
        return None
    for key in ("current", "close", "open"):
        node = side.get(key)
        if isinstance(node, dict) and node.get("odds") not in (None, ""):
            try:
                return int(str(node["odds"]).replace("+", ""))
            except ValueError:
                continue
    if side.get("odds") not in (None, ""):
        try:
            return int(str(side["odds"]).replace("+", ""))
        except ValueError:
            return None
    return None


def parse_scoreboard(payload: dict[str, Any]) -> list[EspnGame]:
    games: list[EspnGame] = []
    for event in payload.get("events") or []:
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        by_side = {
            c.get("homeAway"): (c.get("team") or {}).get("abbreviation")
            for c in comp.get("competitors") or []
        }
        odds_list = comp.get("odds") or []
        if not odds_list or "home" not in by_side or "away" not in by_side:
            continue
        odds = odds_list[0]
        ml = odds.get("moneyline") or {}
        home_am = _american(ml.get("home")) or _american(odds.get("homeTeamOdds") or {})
        away_am = _american(ml.get("away")) or _american(odds.get("awayTeamOdds") or {})
        if home_am is None or away_am is None:
            continue
        games.append(
            EspnGame(
                away_abbr=str(by_side["away"]),
                home_abbr=str(by_side["home"]),
                start_time=_parse_ts(comp.get("date") or event.get("date")),
                provider=str((odds.get("provider") or {}).get("name") or "espn"),
                home_american=home_am,
                away_american=away_am,
            )
        )
    return games


@dataclass
class EspnScraper:
    base_url: str = DEFAULT_BASE_URL
    sport_path: str = "baseball/mlb"
    min_interval_s: float = 1.0
    timeout_s: float = 20.0
    transport: httpx.AsyncBaseTransport | None = None
    _client: httpx.AsyncClient = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _last: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_s,
            transport=self.transport,
            headers={"User-Agent": _BROWSER_UA, "Accept": "application/json"},
        )

    @property
    def name(self) -> str:
        return "espn"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def scoreboard(self, date_yyyymmdd: str) -> list[EspnGame]:
        async with self._lock:
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            r = await self._client.get(
                f"/{self.sport_path}/scoreboard", params={"dates": date_yyyymmdd}
            )
            self._last = time.monotonic()
            r.raise_for_status()
            return parse_scoreboard(r.json())


def et_date_str(dt: datetime) -> str:
    from zoneinfo import ZoneInfo

    return dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")


def now_et_dates() -> list[str]:
    now = datetime.now(UTC)
    from datetime import timedelta

    return sorted({et_date_str(now), et_date_str(now + timedelta(days=1))})
