"""Kalshi MLB moneyline reader (read-only, unauthenticated market data).

Parses the ``KXMLBGAME`` series into games (each an event with one market per
team, YES = that team wins) and computes each team's win probability from the
order-book mid. No auth needed for market data on api.elections.kalshi.com;
no order path anywhere here.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal

from thorp.common.records import JsonDict
from thorp.recorder.kalshi.rest import KalshiRestClient
from thorp.tracker.models import KalshiGame
from thorp.tracker.teams_mlb import canon

logger = logging.getLogger("thorp.tracker")

# KXMLBGAME-<YY><MON><DD><HHMM><TEAMS>  e.g. KXMLBGAME-26JUL231840KCDET
_EVENT_RE = re.compile(r"^KXMLBGAME-(\d{2})([A-Z]{3})(\d{2})\d{4}[A-Z]+$")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_event_date(event_ticker: str) -> date | None:
    m = _EVENT_RE.match(event_ticker)
    if not m:
        return None
    yy, mon, dd = m.group(1), m.group(2), m.group(3)
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        return date(2000 + int(yy), month, int(dd))
    except ValueError:
        return None


def team_from_ticker(ticker: str) -> str | None:
    """Canonical team from a market ticker's suffix (e.g. ...-KC -> 'KC')."""
    return canon(ticker.rsplit("-", 1)[-1])


def orderbook_bbo(
    payload: JsonDict,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(yes_bid, yes_ask, mid) in dollars from a Kalshi order-book response.

    yes best bid = highest resting buy-YES price; yes best ask = 100 - highest
    resting buy-NO price (both in cents). Any element may be None if that side
    is empty.
    """
    book = payload.get("orderbook") or {}
    yes = book.get("yes") or []
    no = book.get("no") or []
    best_bid = max((int(p) for p, _ in yes), default=None)
    best_no = max((int(p) for p, _ in no), default=None)
    bid = Decimal(best_bid) / 100 if best_bid is not None else None
    ask = (Decimal(100 - best_no) / 100) if best_no is not None else None
    mid: Decimal | None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2
    else:
        mid = bid if bid is not None else ask
    return bid, ask, mid


def orderbook_mid(payload: JsonDict) -> Decimal | None:
    """YES mid (dollars), or None if the book is empty. See ``orderbook_bbo``."""
    return orderbook_bbo(payload)[2]


class KalshiMlbClient:
    def __init__(self, rest: KalshiRestClient, series: str = "KXMLBGAME") -> None:
        self._rest = rest
        self._series = series

    async def list_games(self) -> dict[str, KalshiGame]:
        markets = await self._rest.get_open_markets(self._series)
        games: dict[str, dict[str, dict[str, str]]] = {}
        for m in markets:
            ticker = str(m.get("ticker", ""))
            event = str(m.get("event_ticker", ""))
            team = team_from_ticker(ticker)
            if not event or team is None:
                continue
            g = games.setdefault(event, {"markets": {}, "names": {}})
            g["markets"][team] = ticker
            g["names"][team] = str(m.get("yes_sub_title") or team)
        result: dict[str, KalshiGame] = {}
        for event, g in games.items():
            if len(g["markets"]) < 2:
                continue  # need both teams to define a game
            result[event] = KalshiGame(
                event_ticker=event,
                game_date=parse_event_date(event),
                market_by_team=g["markets"],
                name_by_team=g["names"],
            )
        return result

    async def team_prob(self, market_ticker: str) -> Decimal | None:
        payload = await self._rest.get_orderbook(market_ticker)
        return orderbook_mid(payload)

    async def team_book(
        self, market_ticker: str
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        """(yes_bid, yes_ask, mid) in dollars for one team's market."""
        payload = await self._rest.get_orderbook(market_ticker)
        return orderbook_bbo(payload)
