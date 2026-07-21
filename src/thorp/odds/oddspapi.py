"""OddsPapi provider (Doc 13 §3).

API contract (researched from oddspapi.io/en/docs, July 2026):
- Base ``https://api.oddspapi.io/v4``; API key as a **query param** ``apiKey``.
- ``GET /fixtures?sportId&from&to`` — fixtures in a window.
- ``GET /odds?fixtureId&bookmakers=pinnacle,...&oddsFormat=decimal`` — live odds,
  nested ``bookmakerOdds[slug] -> markets[id] -> outcomes[id] -> players["0"] -> price``.

**[VERIFY on first live call]** the exact field names, market/outcome id maps,
and fixture schema against a real response — they're isolated in ``_normalize_*``
below and every record keeps the verbatim payload in ``raw``, so a mismatch is a
one-function fix, not silent corruption. Unrecognized markets/outcomes are kept
with their raw ids rather than dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from thorp.common.records import JsonDict
from thorp.odds.types import Fixture, OddsQuoteRecord

# OddsPapi market/outcome ids -> normalized labels. Extend as verified per sport.
# 101 = Full Time Result (1X2). US moneyline markets use other ids [VERIFY].
_MARKET_LABELS = {"101": "moneyline"}
_OUTCOME_LABELS = {"101": "home", "102": "draw", "103": "away"}


class OddsPapiProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.oddspapi.io/v4",
        odds_format: str = "decimal",
        timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._odds_format = odds_format
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

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
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        result: JsonDict = response.json()
        return result


def _normalize_fixtures(payload: JsonDict, sport: str) -> list[Fixture]:
    raw_fixtures = payload.get("fixtures") or payload.get("data") or []
    fixtures: list[Fixture] = []
    for fx in raw_fixtures:
        fid = fx.get("fixtureId") or fx.get("id")
        if fid is None:
            continue
        fixtures.append(
            Fixture(
                provider="oddspapi",
                fixture_id=str(fid),
                sport=sport,
                start_time=_parse_ts(fx.get("startTime") or fx.get("startsAt")),
                home=_participant(fx, "home"),
                away=_participant(fx, "away"),
                raw=fx,
            )
        )
    return fixtures


def _normalize_quotes(
    payload: JsonDict, fixture_id: str, sport: str, fetched_ts: datetime
) -> list[OddsQuoteRecord]:
    start_time = _parse_ts(payload.get("startTime") or payload.get("startsAt"))
    book_odds = payload.get("bookmakerOdds") or {}
    quotes: list[OddsQuoteRecord] = []
    for slug, book in book_odds.items():
        markets = (book or {}).get("markets") or {}
        for market_id, market in markets.items():
            market_label = _MARKET_LABELS.get(str(market_id), f"market_{market_id}")
            outcomes = (market or {}).get("outcomes") or {}
            for outcome_id, outcome in outcomes.items():
                price = _extract_price(outcome)
                if price is None:
                    continue
                decimal_odds = _to_decimal(price)
                if decimal_odds is None or decimal_odds <= 1:
                    continue
                quotes.append(
                    OddsQuoteRecord(
                        provider="oddspapi",
                        bookmaker=str(slug),
                        fixture_id=fixture_id,
                        sport=sport,
                        market=market_label,
                        outcome=_OUTCOME_LABELS.get(str(outcome_id), f"outcome_{outcome_id}"),
                        decimal_odds=decimal_odds,
                        implied_prob=(Decimal(1) / decimal_odds),
                        start_time=start_time,
                        fetched_ts=fetched_ts,
                        raw={"bookmaker": slug, "market_id": market_id, "outcome": outcome},
                    )
                )
    return quotes


def _extract_price(outcome: Any) -> Any:
    if not isinstance(outcome, dict):
        return None
    players = outcome.get("players")
    if isinstance(players, dict) and "0" in players:
        return players["0"].get("price")
    return outcome.get("price")


def _participant(fx: JsonDict, side: str) -> str | None:
    value = fx.get(side) or fx.get(f"{side}Team") or fx.get(f"{side}Participant")
    if isinstance(value, dict):
        name = value.get("name")
        return str(name) if name is not None else None
    return str(value) if value is not None else None


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
