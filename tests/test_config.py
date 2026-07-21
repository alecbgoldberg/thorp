"""RecorderConfig TOML loading: defaults, overrides, and hard errors."""

from pathlib import Path

import pytest

from thorp.recorder.config import RecorderConfig


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "recorder.toml"
    path.write_text(text)
    return path


def test_minimal_config_uses_defaults(tmp_path: Path) -> None:
    cfg = RecorderConfig.load(
        write(tmp_path, '[kalshi]\nseries_tickers = ["KXMLBGAME"]\n')
    )
    assert cfg.environment == "demo"
    assert cfg.series_tickers == ("KXMLBGAME",)
    assert cfg.rest_url == "https://demo-api.kalshi.co/trade-api/v2"
    assert cfg.ws_url == "wss://demo-api.kalshi.co/trade-api/ws/v2"
    assert cfg.data_dir == Path("data/raw")
    assert cfg.snapshot_interval_s == 60.0


def test_full_config_overrides(tmp_path: Path) -> None:
    cfg = RecorderConfig.load(
        write(
            tmp_path,
            """
[recorder]
data_dir = "/var/thorp/raw"
environment = "prod"
snapshot_interval_s = 30
discovery_interval_s = 120
fsync_interval_s = 1

[kalshi]
series_tickers = ["KXNFLGAME", "KXNBA"]

[kalshi.endpoints.prod]
rest = "https://example.test/api"
ws = "wss://example.test/ws"
""",
        )
    )
    assert cfg.environment == "prod"
    assert cfg.rest_url == "https://example.test/api"
    assert cfg.ws_url == "wss://example.test/ws"
    assert cfg.data_dir == Path("/var/thorp/raw")
    assert cfg.snapshot_interval_s == 30.0
    assert cfg.discovery_interval_s == 120.0
    assert cfg.fsync_interval_s == 1.0
    assert cfg.series_tickers == ("KXNFLGAME", "KXNBA")


def test_prod_defaults_use_elections_host(tmp_path: Path) -> None:
    # api.elections.kalshi.com is the live host (confirmed 2026-07-21);
    # the older api.kalshi.com no longer resolves.
    cfg = RecorderConfig.load(
        write(tmp_path, '[recorder]\nenvironment = "prod"\n[kalshi]\nseries_tickers = ["X"]\n')
    )
    assert cfg.rest_url == "https://api.elections.kalshi.com/trade-api/v2"
    assert cfg.ws_url == "wss://api.elections.kalshi.com/trade-api/ws/v2"


def test_empty_series_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="series_tickers"):
        RecorderConfig.load(write(tmp_path, "[kalshi]\nseries_tickers = []\n"))


def test_unknown_environment_without_endpoints_is_an_error(tmp_path: Path) -> None:
    toml = '[recorder]\nenvironment = "staging"\n[kalshi]\nseries_tickers = ["X"]\n'
    with pytest.raises(ValueError, match="no endpoints"):
        RecorderConfig.load(write(tmp_path, toml))


def test_example_config_parses() -> None:
    example = Path(__file__).parent.parent / "config" / "recorder.example.toml"
    cfg = RecorderConfig.load(example)
    assert cfg.environment == "demo"
    assert cfg.series_tickers
