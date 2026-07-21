"""Collector configuration (TOML). See config/collector.example.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

KALSHI_REST_DEFAULT = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class CollectorConfig:
    data_dir: Path = Path("data")
    kalshi_rest_url: str = KALSHI_REST_DEFAULT
    kalshi_series: str = "KXMLBGAME"
    pinnacle_league: str = "246"  # MLB
    # Our own rate limiting — the only limit now that we run our own feed.
    pinnacle_min_interval_s: float = 1.0
    # Pinnacle bulk endpoint returns the whole slate in one request, so we can
    # sample the entire slate densely and cheaply.
    sample_interval_s: float = 20.0
    discover_interval_s: float = 300.0
    matchups_ttl_s: float = 300.0
    analyze_interval_s: float = 600.0
    # Collect a game's series across its pregame window and through the game.
    pregame_hours: float = 6.0
    postgame_hours: float = 4.0
    max_games: int = 30

    @classmethod
    def load(cls, path: Path) -> CollectorConfig:
        raw = tomllib.loads(path.read_text())
        c = raw.get("collector", {})
        return cls(
            data_dir=Path(c.get("data_dir", "data")),
            kalshi_rest_url=str(c.get("kalshi_rest_url", KALSHI_REST_DEFAULT)),
            kalshi_series=str(c.get("kalshi_series", "KXMLBGAME")),
            pinnacle_league=str(c.get("pinnacle_league", "246")),
            pinnacle_min_interval_s=float(c.get("pinnacle_min_interval_s", 1.0)),
            sample_interval_s=float(c.get("sample_interval_s", 20.0)),
            discover_interval_s=float(c.get("discover_interval_s", 300.0)),
            matchups_ttl_s=float(c.get("matchups_ttl_s", 300.0)),
            analyze_interval_s=float(c.get("analyze_interval_s", 600.0)),
            pregame_hours=float(c.get("pregame_hours", 6.0)),
            postgame_hours=float(c.get("postgame_hours", 4.0)),
            max_games=int(c.get("max_games", 30)),
        )
