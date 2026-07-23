"""Kalshi MLB reader (read-only market data on api.elections.kalshi.com).

Parses the ``KXMLBGAME`` series into games (each an event with one market per
team, YES = that team wins). No auth needed for market data; no order path.

**Schema note (verified live 2026-07-22).** The elections host uses a
dollar/fixed-point schema, not the older cents integers:
- Market objects carry ``yes_bid_dollars`` / ``yes_ask_dollars`` /
  ``last_price_dollars`` (dollar strings) and ``volume_fp`` /
  ``open_interest_fp``. The bulk ``/markets`` list already includes these, so
  BBO for the whole slate comes from one request.
- Order books are ``orderbook_fp`` with ``yes_dollars`` / ``no_dollars`` arrays
  of ``[price_dollars, size]`` strings (resting buy-YES / buy-NO orders).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from thorp.common.records import JsonDict
from thorp.recorder.kalshi.rest import KalshiRestClient
from thorp.tracker.models import KalshiGame
from thorp.tracker.teams_mlb import canon

logger = logging.getLogger("thorp.tracker")

Level = tuple[Decimal, Decimal]  # (price_dollars, size)

_EVENT_RE = re.compile(r"^KXMLBGAME-(\d{2})([A-Z]{3})(\d{2})\d{4}[A-Z]+$")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_event_date(event_ticker: str) -> date | None:
    m = _EVENT_RE.match(event_ticker)
    if not m:
        return None
    month = _MONTHS.get(m.group(2))
    if month is None:
        return None
    try:
        return date(2000 + int(m.group(1)), month, int(m.group(3)))
    except ValueError:
        return None


def team_from_ticker(ticker: str) -> str | None:
    """Canonical team from a market ticker's suffix (e.g. ...-KC -> 'KC')."""
    return canon(ticker.rsplit("-", 1)[-1])


def _dollars(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _fp(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MarketQuote:
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    mid: Decimal | None
    last: Decimal | None
    volume: float | None
    open_interest: float | None


def market_quote(m: JsonDict) -> MarketQuote:
    """BBO + last + volume/OI from a Kalshi market object (dollar/fp schema)."""
    bid = _dollars(m.get("yes_bid_dollars"))
    ask = _dollars(m.get("yes_ask_dollars"))
    if bid is not None and ask is not None:
        mid: Decimal | None = (bid + ask) / 2
    else:
        mid = bid if bid is not None else ask
    return MarketQuote(
        yes_bid=bid,
        yes_ask=ask,
        mid=mid,
        last=_dollars(m.get("last_price_dollars")),
        volume=_fp(m.get("volume_fp")),
        open_interest=_fp(m.get("open_interest_fp")),
    )


def orderbook_levels(payload: JsonDict, top: int = 10) -> tuple[list[Level], list[Level]]:
    """(yes_levels, no_levels), best price first, from an ``orderbook_fp`` body.

    ``yes_dollars`` = resting buy-YES bids; ``no_dollars`` = resting buy-NO bids.
    """
    obfp = payload.get("orderbook_fp") or {}

    def parse(arr: object) -> list[Level]:
        levels: list[Level] = []
        rows = arr if isinstance(arr, list) else []
        for row in rows:
            price, size = _dollars(row[0]), _dollars(row[1])
            if price is not None and size is not None:
                levels.append((price, size))
        levels.sort(key=lambda lv: lv[0], reverse=True)
        return levels[:top]

    return parse(obfp.get("yes_dollars")), parse(obfp.get("no_dollars"))


def orderbook_bbo(
    payload: JsonDict,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(yes_bid, yes_ask, mid) from an order book. yes_ask = 1 - best buy-NO."""
    yes, no = orderbook_levels(payload, top=1)
    bid = yes[0][0] if yes else None
    best_no = no[0][0] if no else None
    ask = (Decimal(1) - best_no) if best_no is not None else None
    if bid is not None and ask is not None:
        mid: Decimal | None = (bid + ask) / 2
    else:
        mid = bid if bid is not None else ask
    return bid, ask, mid


def orderbook_mid(payload: JsonDict) -> Decimal | None:
    return orderbook_bbo(payload)[2]


def games_from_markets(markets: list[JsonDict]) -> dict[str, KalshiGame]:
    grouped: dict[str, dict[str, dict[str, str]]] = {}
    for m in markets:
        ticker = str(m.get("ticker", ""))
        event = str(m.get("event_ticker", ""))
        team = team_from_ticker(ticker)
        if not event or team is None:
            continue
        g = grouped.setdefault(event, {"markets": {}, "names": {}})
        g["markets"][team] = ticker
        g["names"][team] = str(m.get("yes_sub_title") or team)
    result: dict[str, KalshiGame] = {}
    for event, g in grouped.items():
        if len(g["markets"]) < 2:
            continue
        result[event] = KalshiGame(
            event_ticker=event,
            game_date=parse_event_date(event),
            market_by_team=g["markets"],
            name_by_team=g["names"],
        )
    return result


class KalshiMlbClient:
    def __init__(self, rest: KalshiRestClient, series: str = "KXMLBGAME") -> None:
        self._rest = rest
        self._series = series

    async def fetch_markets(self) -> list[JsonDict]:
        """All open markets for the series (one request; includes BBO/volume)."""
        return await self._rest.get_open_markets(self._series)

    async def fetch_markets_for_series(self, series: str) -> list[JsonDict]:
        """All open markets for an arbitrary series (e.g. KXMLBSPREAD/KXMLBTOTAL)."""
        return await self._rest.get_open_markets(series)

    async def list_games(self) -> dict[str, KalshiGame]:
        return games_from_markets(await self.fetch_markets())

    async def orderbook(self, market_ticker: str, top: int = 10) -> tuple[list[Level], list[Level]]:
        payload = await self._rest.get_orderbook(market_ticker)
        return orderbook_levels(payload, top=top)

    async def team_prob(self, market_ticker: str) -> Decimal | None:
        payload = await self._rest.get_orderbook(market_ticker)
        return orderbook_mid(payload)

    async def team_book(
        self, market_ticker: str
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        payload = await self._rest.get_orderbook(market_ticker)
        return orderbook_bbo(payload)
