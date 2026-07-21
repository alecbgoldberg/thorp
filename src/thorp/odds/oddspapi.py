"""OddsPapi provider (Doc 13 §3), verified against live responses 2026-07-21.

Confirmed contract:
- Base ``https://api.oddspapi.io/v4``; API key as a **query param** ``apiKey``.
- ``GET /sports`` -> ``[{"sportId":13,"slug":"baseball",...}]`` (baseball = 13).
- ``GET /fixtures?sportId=13&from&to`` -> list of fixtures with
  ``participant1Abbr/Name``, ``participant2Abbr/Name``, ``tournamentName``
  ("MLB"), ``startTime``, ``hasOdds``, ``externalProviders.pinnacleId``.
- ``GET /odds?fixtureId&bookmakers=pinnacle&oddsFormat=decimal`` ->
  ``bookmakerOdds[slug].markets[id].outcomes[id].players["0"].price``, where each
  ``players["0"]`` also carries ``bookmakerOutcomeId``. The **moneyline** is the
  market whose two outcomes' ``bookmakerOutcomeId`` are exactly ``home``/``away``
  (market 131 for MLB; ids are sport-specific, so we detect by home/away, not id).

Cloudflare occasionally 1010-bans non-browser User-Agents and the API rate-limits
with ``429 {retryAfter}``; the client sets a browser UA and retries 429 once.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from thorp.common.records import JsonDict
from thorp.odds.types import Fixture, OddsQuoteRecord

logger = logging.getLogger("thorp.odds")

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class OddsPapiProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.oddspapi.io/v4",
        odds_format: str = "decimal",
        timeout_s: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._odds_format = odds_format
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            transport=transport,
            headers={"User-Agent": _BROWSER_UA, "Accept": "application/json"},
        )

    @property
    def name(self) -> str:
        return "oddspapi"

    async def list_fixtures(self, sport: str, start: datetime, end: datetime) -> list[Fixture]:
        payload = await self._get(
            "/fixtures",
            {"sportId": sport, "from": start.date().isoformat(), "to": end.date().isoformat()},
        )
        return _normalize_fixtures(payload, sport)

    async def fetch_quotes(
        self, fixture_id: str, sport: str, bookmakers: list[str]
    ) -> list[OddsQuoteRecord]:
        payload = await self._get(
            "/odds",
            {
                "fixtureId": fixture_id,
                "bookmakers": ",".join(bookmakers),
                "oddsFormat": self._odds_format,
            },
        )
        return _normalize_quotes(payload, fixture_id, sport, datetime.now(UTC))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> JsonDict:
        params = {**params, "apiKey": self._api_key}
        for attempt in (1, 2):
            response = await self._client.get(path, params=params)
            if response.status_code == 429 and attempt == 1:
                wait = _retry_after_seconds(response)
                logger.warning("odds 429 rate-limited; waiting %.2fs then retrying", wait)
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            result: JsonDict = response.json()
            return result
        raise RuntimeError("unreachable")  # pragma: no cover


def _retry_after_seconds(response: httpx.Response) -> float:
    try:
        body = response.json()
        ms = body.get("error", {}).get("retryMs")
        if ms is not None:
            return min(5.0, float(ms) / 1000 + 0.1)
    except (ValueError, AttributeError, TypeError):
        pass
    return 1.0


def _normalize_fixtures(payload: JsonDict, sport: str) -> list[Fixture]:
    raw_fixtures = payload if isinstance(payload, list) else payload.get("fixtures") or []
    fixtures: list[Fixture] = []
    for fx in raw_fixtures:
        fid = fx.get("fixtureId") or fx.get("id")
        if fid is None:
            continue
        providers = fx.get("externalProviders") or {}
        pinnacle_id = providers.get("pinnacleId")
        fixtures.append(
            Fixture(
                provider="oddspapi",
                fixture_id=str(fid),
                sport=sport,
                tournament=fx.get("tournamentName"),
                start_time=_parse_ts(fx.get("startTime")),
                p1_abbr=fx.get("participant1Abbr"),
                p1_name=fx.get("participant1Name"),
                p2_abbr=fx.get("participant2Abbr"),
                p2_name=fx.get("participant2Name"),
                has_odds=bool(fx.get("hasOdds")),
                pinnacle_id=str(pinnacle_id) if pinnacle_id is not None else None,
                raw=fx,
            )
        )
    return fixtures


def _normalize_quotes(
    payload: JsonDict, fixture_id: str, sport: str, fetched_ts: datetime
) -> list[OddsQuoteRecord]:
    start_time = _parse_ts(payload.get("startTime"))
    book_odds = payload.get("bookmakerOdds") or {}
    quotes: list[OddsQuoteRecord] = []
    for slug, book in book_odds.items():
        markets = (book or {}).get("markets") or {}
        moneyline = _find_moneyline(markets)
        if moneyline is None:
            continue
        for outcome_label, price in moneyline.items():  # "home"/"away" -> decimal
            decimal_odds = _to_decimal(price)
            if decimal_odds is None or decimal_odds <= 1:
                continue
            quotes.append(
                OddsQuoteRecord(
                    provider="oddspapi",
                    bookmaker=str(slug),
                    fixture_id=fixture_id,
                    sport=sport,
                    market="moneyline",
                    outcome=outcome_label,
                    decimal_odds=decimal_odds,
                    implied_prob=(Decimal(1) / decimal_odds),
                    start_time=start_time,
                    fetched_ts=fetched_ts,
                    raw={"bookmaker": slug, "outcome": outcome_label, "price": price},
                )
            )
    return quotes


def _find_moneyline(markets: JsonDict) -> dict[str, Any] | None:
    """Return ``{"home": price, "away": price}`` for the 2-way moneyline market.

    Detected by outcome labels being exactly {home, away} — robust across sports,
    unlike a hardcoded market id. Prefers a full-game market (``/0/mon`` in the
    bookmaker market id) if several qualify.
    """
    candidates: list[tuple[bool, dict[str, Any]]] = []
    for market in markets.values():
        outcomes = (market or {}).get("outcomes") or {}
        labeled: dict[str, Any] = {}
        for outcome in outcomes.values():
            player = (outcome.get("players") or {}).get("0") or {}
            label = player.get("bookmakerOutcomeId")
            price = player.get("price")
            if label in ("home", "away") and price is not None:
                labeled[label] = price
        if set(labeled) == {"home", "away"}:
            full_game = "/0/mon" in str(market.get("bookmakerMarketId", ""))
            candidates.append((full_game, labeled))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)  # full-game first
    return candidates[0][1]


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
