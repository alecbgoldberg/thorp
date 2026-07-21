"""MLB moneyline tracker configuration (TOML). See config/tracker.example.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

KALSHI_REST_DEFAULT = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class TrackerConfig:
    data_dir: Path = Path("data")
    kalshi_rest_url: str = KALSHI_REST_DEFAULT
    kalshi_series: str = "KXMLBGAME"
    sport_id: str = "13"  # OddsPapi baseball
    bookmaker: str = "pinnacle"
    secrets_file: Path = Path("secrets/odds.env")
    api_key_env: str = "THORP_ODDSPAPI_API_KEY"
    # Kalshi is free/dense; Pinnacle is budget-limited so poll it sparsely and
    # only in the active window around first pitch (where the line actually
    # moves), to make 250 calls/month cover several games instead of one day.
    kalshi_interval_s: float = 30.0
    oddspapi_interval_s: float = 180.0  # 3 min, only within the active window
    analyze_interval_s: float = 300.0
    discover_interval_s: float = 1800.0  # re-match Kalshi games every 30 min (free)
    fixtures_ttl_s: float = 43200.0  # refetch OddsPapi fixtures at most every 12h
    active_window_hours: float = 3.0  # sample Pinnacle within this of first pitch
    monthly_odds_budget: int = 250
    max_games: int = 1  # focus budget on one game densely by default
    fixture_lookahead_hours: float = 48.0
    # Lead/lag grid — coarser than the research default since Pinnacle sampling
    # is minute-scale, not second-scale, under the budget.
    analyze_step_s: float = 30.0
    analyze_max_lag_s: float = 1800.0

    @classmethod
    def load(cls, path: Path) -> TrackerConfig:
        raw = tomllib.loads(path.read_text())
        t = raw.get("tracker", {})
        return cls(
            data_dir=Path(t.get("data_dir", "data")),
            kalshi_rest_url=str(t.get("kalshi_rest_url", KALSHI_REST_DEFAULT)),
            kalshi_series=str(t.get("kalshi_series", "KXMLBGAME")),
            sport_id=str(t.get("sport_id", "13")),
            bookmaker=str(t.get("bookmaker", "pinnacle")),
            secrets_file=Path(t.get("secrets_file", "secrets/odds.env")),
            api_key_env=str(t.get("api_key_env", "THORP_ODDSPAPI_API_KEY")),
            kalshi_interval_s=float(t.get("kalshi_interval_s", 30.0)),
            oddspapi_interval_s=float(t.get("oddspapi_interval_s", 180.0)),
            analyze_interval_s=float(t.get("analyze_interval_s", 300.0)),
            discover_interval_s=float(t.get("discover_interval_s", 1800.0)),
            fixtures_ttl_s=float(t.get("fixtures_ttl_s", 43200.0)),
            active_window_hours=float(t.get("active_window_hours", 3.0)),
            monthly_odds_budget=int(t.get("monthly_odds_budget", 250)),
            max_games=int(t.get("max_games", 1)),
            fixture_lookahead_hours=float(t.get("fixture_lookahead_hours", 48.0)),
            analyze_step_s=float(t.get("analyze_step_s", 30.0)),
            analyze_max_lag_s=float(t.get("analyze_max_lag_s", 1800.0)),
        )
