"""Odds provider: config, factory swap seam, and OddsPapi normalization."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from thorp.odds.config import OddsConfig
from thorp.odds.oddspapi import OddsPapiProvider
from thorp.odds.provider import build_provider


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "odds.toml"
    path.write_text(text)
    return path


def test_config_defaults_resolve_provider(tmp_path: Path) -> None:
    cfg = OddsConfig.load(write(tmp_path, '[odds]\nsports = ["baseball_mlb"]\n'))
    assert cfg.provider == "oddspapi"
    assert cfg.base_url == "https://api.oddspapi.io/v4"
    assert cfg.api_key_env == "THORP_ODDSPAPI_API_KEY"
    assert cfg.bookmakers == ("pinnacle",)
    assert cfg.sports == ("baseball_mlb",)


def test_config_requires_sports(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sports"):
        OddsConfig.load(write(tmp_path, "[odds]\nsports = []\n"))


def test_config_unknown_provider_needs_explicit_urls(tmp_path: Path) -> None:
    toml = '[odds]\nprovider = "mystery"\nsports = ["x"]\n'
    with pytest.raises(ValueError, match="base_url"):
        OddsConfig.load(write(tmp_path, toml))


def test_example_config_parses() -> None:
    cfg = OddsConfig.load(Path(__file__).parent.parent / "config" / "odds.example.toml")
    assert cfg.provider == "oddspapi" and cfg.bookmakers == ("pinnacle",)


def test_build_provider_swap_seam(tmp_path: Path) -> None:
    cfg = OddsConfig.load(write(tmp_path, '[odds]\nsports = ["x"]\n'))
    provider = build_provider(cfg, api_key="k")
    assert provider.name == "oddspapi"

    unknown = OddsConfig(
        provider="mystery", base_url="http://x", api_key_env="X", sports=("x",),
        bookmakers=("pinnacle",),
    )
    with pytest.raises(ValueError, match="unknown odds provider"):
        build_provider(unknown, api_key="k")


async def test_oddspapi_fetch_quotes_normalizes() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        assert request.url.path.endswith("/odds")
        return httpx.Response(
            200,
            json={
                "startTime": "2026-07-20T23:05:00Z",
                "bookmakerOdds": {
                    "pinnacle": {
                        "markets": {
                            "101": {
                                "outcomes": {
                                    "101": {"players": {"0": {"price": "1.90"}}},
                                    "103": {"players": {"0": {"price": "2.10"}}},
                                }
                            }
                        }
                    }
                },
            },
        )

    provider = OddsPapiProvider(api_key="secret", transport=httpx.MockTransport(handler))
    quotes = await provider.fetch_quotes("fix-1", "baseball_mlb", ["pinnacle"])
    await provider.aclose()

    assert captured["apiKey"] == "secret"
    assert captured["bookmakers"] == "pinnacle"
    assert captured["oddsFormat"] == "decimal"
    assert len(quotes) == 2
    home = next(q for q in quotes if q.outcome == "home")
    assert home.bookmaker == "pinnacle"
    assert home.market == "moneyline"
    assert home.decimal_odds == Decimal("1.90")
    # implied prob = 1/1.90, vig-inclusive
    assert abs(float(home.implied_prob) - 1 / 1.90) < 1e-9
    assert home.fixture_id == "fix-1"
    assert home.start_time == datetime(2026, 7, 20, 23, 5, tzinfo=UTC)
    assert home.raw is not None  # verbatim payload retained


async def test_oddspapi_skips_bad_prices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "bookmakerOdds": {
                    "pinnacle": {
                        "markets": {
                            "101": {
                                "outcomes": {
                                    "101": {"players": {"0": {"price": "1.00"}}},  # <= 1, drop
                                    "103": {"players": {"0": {"price": "abc"}}},  # unparseable
                                    "102": {"players": {"0": {"price": "3.5"}}},  # keep
                                }
                            }
                        }
                    }
                }
            },
        )

    provider = OddsPapiProvider(api_key="k", transport=httpx.MockTransport(handler))
    quotes = await provider.fetch_quotes("f", "s", ["pinnacle"])
    await provider.aclose()
    assert [q.outcome for q in quotes] == ["draw"]  # only the valid 3.5 survives


async def test_oddspapi_list_fixtures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/fixtures")
        return httpx.Response(
            200,
            json={"fixtures": [
                {"fixtureId": "f1", "startTime": "2026-07-21T00:00:00Z",
                 "home": {"name": "NYY"}, "away": {"name": "BOS"}},
                {"id": "f2"},  # minimal, alternate id key
            ]},
        )

    provider = OddsPapiProvider(api_key="k", transport=httpx.MockTransport(handler))
    fixtures = await provider.list_fixtures("baseball_mlb", datetime.now(UTC), datetime.now(UTC))
    await provider.aclose()
    assert [f.fixture_id for f in fixtures] == ["f1", "f2"]
    assert fixtures[0].home == "NYY" and fixtures[0].away == "BOS"
