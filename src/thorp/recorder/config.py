"""Recorder configuration (TOML). See config/recorder.example.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# Doc 1 §1.1 endpoints. [VERIFY on first live connect] — override per-environment
# in the TOML under [kalshi.endpoints.<env>] if these have moved.
DEFAULT_ENDPOINTS: dict[str, dict[str, str]] = {
    "prod": {
        "rest": "https://api.kalshi.com/trade-api/v2",
        "ws": "wss://api.kalshi.com/trade-api/ws/v2",
    },
    "demo": {
        "rest": "https://demo-api.kalshi.co/trade-api/v2",
        "ws": "wss://demo-api.kalshi.co/trade-api/ws/v2",
    },
}


@dataclass(frozen=True)
class RecorderConfig:
    data_dir: Path
    environment: str
    series_tickers: tuple[str, ...]
    rest_url: str
    ws_url: str
    snapshot_interval_s: float = 60.0
    discovery_interval_s: float = 300.0
    fsync_interval_s: float = 5.0
    api_key_id_env: str = "THORP_KALSHI_API_KEY_ID"
    private_key_path_env: str = "THORP_KALSHI_PRIVATE_KEY_PATH"

    @classmethod
    def load(cls, path: Path) -> RecorderConfig:
        raw = tomllib.loads(path.read_text())
        rec = raw.get("recorder", {})
        kalshi = raw.get("kalshi", {})

        environment = str(rec.get("environment", "demo"))
        endpoints = {
            **DEFAULT_ENDPOINTS.get(environment, {}),
            **kalshi.get("endpoints", {}).get(environment, {}),
        }
        if "rest" not in endpoints or "ws" not in endpoints:
            raise ValueError(
                f"no endpoints for environment {environment!r}; "
                f"add [kalshi.endpoints.{environment}] with 'rest' and 'ws' keys"
            )
        series = [str(s) for s in kalshi.get("series_tickers", [])]
        if not series:
            raise ValueError("kalshi.series_tickers must be a non-empty list")

        return cls(
            data_dir=Path(rec.get("data_dir", "data/raw")),
            environment=environment,
            series_tickers=tuple(series),
            rest_url=endpoints["rest"],
            ws_url=endpoints["ws"],
            snapshot_interval_s=float(rec.get("snapshot_interval_s", 60.0)),
            discovery_interval_s=float(rec.get("discovery_interval_s", 300.0)),
            fsync_interval_s=float(rec.get("fsync_interval_s", 5.0)),
            api_key_id_env=str(kalshi.get("api_key_id_env", "THORP_KALSHI_API_KEY_ID")),
            private_key_path_env=str(
                kalshi.get("private_key_path_env", "THORP_KALSHI_PRIVATE_KEY_PATH")
            ),
        )
