"""Cross-venue event matcher: Kalshi contract <-> Polymarket US contract (Doc 17).

To cross Kalshi and Polymarket we must be certain both legs are the *same*
outcome of the *same* game. Both venues encode that in their identifiers:

- Kalshi market ticker: ``KXMLBGAME-26JUL231840KCDET-KC`` -> sport MLB,
  date 2026-07-23, outcome team KC.
- Polymarket US symbol: ``tec-mlb-...-2026-07-23-kc`` -> sport MLB, date, team.
  (Format from docs.polymarket.us; **[VERIFY]** the exact MLB symbol against a
  real instrument once API access is granted — the parser is deliberately
  tolerant of the middle "event" segment.)

We reduce both to a canonical ``EventOutcome`` (sport, date, outcome team) and
match on equality. Doubleheaders (same teams twice in a day) are the known edge
case — flagged for game-number/time disambiguation once real symbols are seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from thorp.tracker.kalshi_mlb import parse_event_date, team_from_ticker
from thorp.tracker.teams_mlb import canon

_SERIES_RE = re.compile(r"^KX([A-Z]+)GAME-")
# Kalshi series ticker sport code -> canonical sport slug (matches Polymarket).
_SPORT_ALIASES = {"mlb": "mlb", "nfl": "nfl", "nba": "nba", "nhl": "nhl"}


@dataclass(frozen=True)
class EventOutcome:
    sport: str  # canonical slug, e.g. "mlb"
    date: date
    outcome_team: str  # canonical team abbr, e.g. "KC"


def _sport_from_kalshi(ticker: str) -> str | None:
    m = _SERIES_RE.match(ticker)
    if not m:
        return None
    return _SPORT_ALIASES.get(m.group(1).lower())


def from_kalshi_ticker(market_ticker: str) -> EventOutcome | None:
    sport = _sport_from_kalshi(market_ticker)
    event_ticker = market_ticker.rsplit("-", 1)[0]  # drop the -TEAM outcome suffix
    game_date = parse_event_date(event_ticker)
    outcome = team_from_ticker(market_ticker)
    if sport is None or game_date is None or outcome is None:
        return None
    return EventOutcome(sport=sport, date=game_date, outcome_team=outcome)


def from_polymarket_symbol(symbol: str) -> EventOutcome | None:
    parts = symbol.lower().split("-")
    if len(parts) < 6:  # tec, sport, ...event..., YYYY, MM, DD, team
        return None
    sport = _SPORT_ALIASES.get(parts[1])
    outcome = canon(parts[-1])
    try:
        game_date = date.fromisoformat("-".join(parts[-4:-1]))
    except ValueError:
        return None
    if sport is None or outcome is None:
        return None
    return EventOutcome(sport=sport, date=game_date, outcome_team=outcome)


def same_contract(a: EventOutcome | None, b: EventOutcome | None) -> bool:
    return a is not None and b is not None and a == b


@dataclass(frozen=True)
class CrossVenueContract:
    """One outcome tradeable on both venues (verified to be the same contract)."""

    outcome: EventOutcome
    kalshi_ticker: str
    polymarket_symbol: str


def match_symbols(
    kalshi_ticker: str, polymarket_symbols: list[str]
) -> CrossVenueContract | None:
    """Find the Polymarket symbol that is the same contract as a Kalshi market."""
    kalshi_eo = from_kalshi_ticker(kalshi_ticker)
    if kalshi_eo is None:
        return None
    for symbol in polymarket_symbols:
        if same_contract(kalshi_eo, from_polymarket_symbol(symbol)):
            return CrossVenueContract(
                outcome=kalshi_eo, kalshi_ticker=kalshi_ticker, polymarket_symbol=symbol
            )
    return None
