"""Odds-capture configuration (TOML). See config/odds.example.toml.

Provider-agnostic: ``provider`` selects the implementation and ``api_key_env``
names the env var its key lives in, so switching vendors is config-only.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# Per-provider defaults (base URL + the env var its key lives in). Adding a
# provider here + an impl in provider.build_provider is the whole swap surface.
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "oddspapi": {
        "base_url": "https://api.oddspapi.io/v4",
        "api_key_env": "THORP_ODDSPAPI_API_KEY",
    },
}


@dataclass(frozen=True)
class OddsConfig:
    provider: str
    base_url: str
    api_key_env: str
    sports: tuple[str, ...]
    bookmakers: tuple[str, ...]
    data_dir: Path = Path("data/raw")
    secrets_file: Path = Path("secrets/odds.env")
    odds_format: str = "decimal"
    poll_interval_s: float = 60.0
    fixture_lookahead_hours: float = 48.0
    fsync_interval_s: float = 5.0

    @classmethod
    def load(cls, path: Path) -> OddsConfig:
        raw = tomllib.loads(path.read_text())
        odds = raw.get("odds", {})
        provider = str(odds.get("provider", "oddspapi"))
        defaults = PROVIDER_DEFAULTS.get(provider, {})
        base_url = str(odds.get("base_url") or defaults.get("base_url", ""))
        api_key_env = str(odds.get("api_key_env") or defaults.get("api_key_env", ""))
        if not base_url or not api_key_env:
            raise ValueError(
                f"provider {provider!r} has no base_url/api_key_env default; "
                f"set them explicitly under [odds]"
            )
        sports = tuple(str(s) for s in odds.get("sports", []))
        if not sports:
            raise ValueError("odds.sports must be a non-empty list")
        bookmakers = tuple(str(b) for b in odds.get("bookmakers", ["pinnacle"]))
        return cls(
            provider=provider,
            base_url=base_url,
            api_key_env=api_key_env,
            sports=sports,
            bookmakers=bookmakers,
            data_dir=Path(odds.get("data_dir", "data/raw")),
            secrets_file=Path(odds.get("secrets_file", "secrets/odds.env")),
            odds_format=str(odds.get("odds_format", "decimal")),
            poll_interval_s=float(odds.get("poll_interval_s", 60.0)),
            fixture_lookahead_hours=float(odds.get("fixture_lookahead_hours", 48.0)),
            fsync_interval_s=float(odds.get("fsync_interval_s", 5.0)),
        )
