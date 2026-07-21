"""Match Kalshi games to OddsPapi fixtures and resolve outcome orientation.

Games match when both sources name the **same two canonical teams** and their
dates agree within a day (time zones/rollover). The reference team both probs
track is the alphabetically-first canonical abbr — a deterministic, source-
independent choice.

OddsPapi moneyline outcomes are labeled ``home``/``away`` with no team identity,
and which participant is home is not reliably given. So the ``home``/``away`` ->
``ref_team`` orientation is resolved **once**, at first paired sample, by picking
the mapping whose Pinnacle P(ref_team) agrees with Kalshi on who's favored, then
locked — so the lead/lag signal is preserved for every later sample rather than
forced into agreement.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from thorp.odds.types import Fixture
from thorp.tracker.models import GameLink, KalshiGame
from thorp.tracker.teams_mlb import canon


def _fixture_teams(fx: Fixture) -> frozenset[str] | None:
    a = canon(fx.p1_abbr or "") or canon(fx.p1_name or "")
    b = canon(fx.p2_abbr or "") or canon(fx.p2_name or "")
    if a and b and a != b:
        return frozenset({a, b})
    return None


def match_games(
    kalshi_games: dict[str, KalshiGame], fixtures: list[Fixture]
) -> list[GameLink]:
    """Pair Kalshi games with MLB OddsPapi fixtures by teams + date."""
    by_teams: dict[frozenset[str], list[Fixture]] = {}
    for fx in fixtures:
        if fx.tournament and fx.tournament != "MLB":
            continue
        teams = _fixture_teams(fx)
        if teams is not None:
            by_teams.setdefault(teams, []).append(fx)

    links: list[GameLink] = []
    for game in kalshi_games.values():
        teams = frozenset(game.market_by_team)
        if len(teams) != 2:
            continue
        candidates = by_teams.get(teams)
        if not candidates:
            continue
        fx = _closest_by_date(game, candidates)
        ref = min(teams)
        a, b = sorted(teams)
        start = fx.start_time
        if start is None and game.game_date is not None:
            start = datetime.combine(game.game_date, time.min, tzinfo=UTC)
        links.append(
            GameLink(
                game_key=f"{game.game_date}:{a}-{b}",
                teams=(a, b),
                ref_team=ref,
                kalshi_event=game.event_ticker,
                kalshi_market_by_team=dict(game.market_by_team),
                oddspapi_fixture_id=fx.fixture_id,
                oddspapi_pinnacle_id=fx.pinnacle_id,
                start_time=start,
            )
        )
    return links


def _closest_by_date(game: KalshiGame, fixtures: list[Fixture]) -> Fixture:
    if game.game_date is None:
        return fixtures[0]
    game_date = game.game_date

    def gap(fx: Fixture) -> timedelta:
        if fx.start_time is None:
            return timedelta(days=999)
        return abs(fx.start_time.date() - game_date)

    return min(fixtures, key=gap)


def resolve_ref_prob(
    p_home: float, p_away: float, kalshi_ref_prob: float, locked: str | None
) -> tuple[float, str]:
    """Map Pinnacle home/away probabilities to P(ref_team).

    ``locked`` is the previously chosen orientation ("home"/"away") or None. On
    the first call it picks the orientation minimizing disagreement with Kalshi
    (favorite alignment); once chosen it's returned so the caller can lock it.
    Returns ``(pinnacle_ref_prob, orientation)``.
    """
    if locked == "home":
        return p_home, "home"
    if locked == "away":
        return p_away, "away"
    home_gap = abs(p_home - kalshi_ref_prob)
    away_gap = abs(p_away - kalshi_ref_prob)
    orientation = "home" if home_gap <= away_gap else "away"
    return (p_home if orientation == "home" else p_away), orientation
