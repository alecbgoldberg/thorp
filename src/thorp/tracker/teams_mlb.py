"""MLB team canonicalization.

Kalshi identifies teams by abbreviation in the ticker (``...-KC``) and by city in
``yes_sub_title`` ("Kansas City"); OddsPapi uses full names ("Kansas City
Royals") and its own abbreviations. ``canon`` maps any of these to a single
canonical abbreviation so the two sources' games can be matched.

Ambiguous bare cities (New York, Los Angeles, Chicago) are intentionally *not*
aliased — those must be disambiguated by abbreviation or nickname, never by city
alone, so we never mis-match Yankees for Mets.
"""

from __future__ import annotations

# canonical abbr -> alias tokens (lowercased). Includes nickname, full-ish name,
# city (only when unambiguous), and known abbreviation variants across sources.
_TEAMS: dict[str, list[str]] = {
    "NYY": ["yankees", "new york yankees", "ny yankees", "nyy"],
    "NYM": ["mets", "new york mets", "ny mets", "nym"],
    "BOS": ["red sox", "boston", "boston red sox", "bos"],
    "TB": ["rays", "tampa bay", "tampa bay rays", "tb", "tbr"],
    "TOR": ["blue jays", "toronto", "toronto blue jays", "tor"],
    "BAL": ["orioles", "baltimore", "baltimore orioles", "bal"],
    "CLE": ["guardians", "cleveland", "cleveland guardians", "cle"],
    "MIN": ["twins", "minnesota", "minnesota twins", "min"],
    "DET": ["tigers", "detroit", "detroit tigers", "det"],
    "KC": ["royals", "kansas city", "kansas city royals", "kc", "kan", "kcr"],
    "CWS": ["white sox", "chicago white sox", "cws", "chw"],
    "HOU": ["astros", "houston", "houston astros", "hou"],
    "SEA": ["mariners", "seattle", "seattle mariners", "sea"],
    "TEX": ["rangers", "texas", "texas rangers", "tex"],
    "LAA": ["angels", "los angeles angels", "la angels", "laa", "ana"],
    "ATH": ["athletics", "oakland", "oakland athletics", "ath", "oak"],
    "ATL": ["braves", "atlanta", "atlanta braves", "atl"],
    "PHI": ["phillies", "philadelphia", "philadelphia phillies", "phi"],
    "MIA": ["marlins", "miami", "miami marlins", "mia"],
    "WSH": ["nationals", "washington", "washington nationals", "wsh", "wsn", "was"],
    "MIL": ["brewers", "milwaukee", "milwaukee brewers", "mil"],
    "CHC": ["cubs", "chicago cubs", "chc"],
    "STL": ["cardinals", "st louis", "st. louis", "st louis cardinals", "stl"],
    "CIN": ["reds", "cincinnati", "cincinnati reds", "cin"],
    "PIT": ["pirates", "pittsburgh", "pittsburgh pirates", "pit"],
    "LAD": ["dodgers", "los angeles dodgers", "la dodgers", "lad"],
    "SD": ["padres", "san diego", "san diego padres", "sd", "sdp"],
    "SF": ["giants", "san francisco", "san francisco giants", "sf", "sfg"],
    "ARI": ["diamondbacks", "dbacks", "arizona", "arizona diamondbacks", "ari", "az"],
    "COL": ["rockies", "colorado", "colorado rockies", "col"],
}

_ALIAS_TO_CANON: dict[str, str] = {}
for _abbr, _aliases in _TEAMS.items():
    _ALIAS_TO_CANON[_abbr.lower()] = _abbr
    for _alias in _aliases:
        _ALIAS_TO_CANON[_alias] = _abbr


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace(".", "").split())


def canon(name_or_abbr: str) -> str | None:
    """Canonical abbreviation for a team name/abbr, or None if unrecognized."""
    if not name_or_abbr:
        return None
    return _ALIAS_TO_CANON.get(_normalize(name_or_abbr))
