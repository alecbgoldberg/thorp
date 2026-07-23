"""Kalshi spread/total markets <-> Pinnacle spread/total (careful line mapping).

Kalshi (verified): ``KXMLBSPREAD-<event>-<TEAM><n>`` = "TEAM wins by over
``floor_strike`` runs"; ``KXMLBTOTAL-<event>-<n>`` = "Over ``floor_strike`` runs".
Both events share the ``<date+time+teams>`` suffix with the ``KXMLBGAME`` event.

Mapping to Pinnacle (Doc: match the SAME line, never by name):
- Spread: Kalshi "T wins by over L" == P(T covers -L) == Pinnacle ``(T_side, -L)``.
- Total:  Kalshi "over L"          == P(over L)      == Pinnacle ``totals[L][0]``.

Only exact-line matches are paired; a Kalshi alt line with no Pinnacle
counterpart (or vice versa) is skipped rather than mis-paired.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from thorp.tracker.kalshi_mlb import market_quote
from thorp.tracker.teams_mlb import canon


def spread_event_ticker(kalshi_game_event: str) -> str:
    return kalshi_game_event.replace("KXMLBGAME-", "KXMLBSPREAD-", 1)


def total_event_ticker(kalshi_game_event: str) -> str:
    return kalshi_game_event.replace("KXMLBGAME-", "KXMLBTOTAL-", 1)


def parse_spread_market(m: dict[str, Any]) -> tuple[str, float] | None:
    """(canonical team, line) from a KXMLBSPREAD market, or None."""
    suffix = str(m.get("ticker", "")).rsplit("-", 1)[-1]
    team = canon(suffix.rstrip("0123456789"))
    line = m.get("floor_strike")
    if team is None or line is None:
        return None
    return team, float(line)


def parse_total_market(m: dict[str, Any]) -> float | None:
    line = m.get("floor_strike")
    return float(line) if line is not None else None


@dataclass(frozen=True)
class LinePair:
    kind: str  # "spread" | "total"
    line: float
    selection: str  # spread: team abbr; total: "over"
    kalshi_prob: Decimal | None  # Kalshi YES mid
    pinnacle_prob: float  # de-vigged Pinnacle prob for the same outcome
    edge: float | None  # pinnacle - kalshi (positive => Kalshi cheap)
    ticker: str


def match_spreads(
    kalshi_markets: list[dict[str, Any]],
    pinnacle_spreads: dict[tuple[str, float], float],
    home_team: str,
    away_team: str,
) -> list[LinePair]:
    pairs: list[LinePair] = []
    for m in kalshi_markets:
        parsed = parse_spread_market(m)
        if parsed is None:
            continue
        team, line = parsed
        side = "home" if team == home_team else "away" if team == away_team else None
        if side is None:
            continue
        pin = pinnacle_spreads.get((side, -line))  # "wins by over L" == covers -L
        if pin is None:
            continue
        kmid = market_quote(m).mid
        edge = (pin - float(kmid)) if kmid is not None else None
        pairs.append(LinePair("spread", line, team, kmid, pin,
                              round(edge, 6) if edge is not None else None, str(m.get("ticker"))))
    return pairs


def match_totals(
    kalshi_markets: list[dict[str, Any]],
    pinnacle_totals: dict[float, tuple[float, float]],
) -> list[LinePair]:
    pairs: list[LinePair] = []
    for m in kalshi_markets:
        line = parse_total_market(m)
        if line is None:
            continue
        pin_pair = pinnacle_totals.get(line)
        if pin_pair is None:
            continue
        over_prob = pin_pair[0]  # Kalshi YES = Over
        kmid = market_quote(m).mid
        edge = (over_prob - float(kmid)) if kmid is not None else None
        pairs.append(LinePair("total", line, "over", kmid, over_prob,
                              round(edge, 6) if edge is not None else None, str(m.get("ticker"))))
    return pairs
