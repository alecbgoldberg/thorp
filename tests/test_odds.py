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


def _ml_outcome(label: str, price: str) -> dict:
    return {"players": {"0": {"bookmakerOutcomeId": label, "price": price}}}


def _odds_payload() -> dict:
    # Real OddsPapi shape: moneyline is the market whose outcomes are home/away.
    return {
        "startTime": "2026-07-21T22:40:00.000Z",
        "bookmakerOdds": {
            "pinnacle": {
                "markets": {
                    "1366": {  # a spread — must be ignored
                        "bookmakerMarketId": "altLine/3/246/x/spreads",
                        "outcomes": {
                            "1366": _ml_outcome("-2.0/home", "3.06"),
                            "1367": _ml_outcome("-2.0/away", "1.404"),
                        },
                    },
                    "131": {  # full-game moneyline
                        "bookmakerMarketId": "line/3/246/x/0/mon",
                        "outcomes": {
                            "131": _ml_outcome("home", "1.763"),
                            "132": _ml_outcome("away", "2.19"),
                        },
                    },
                    "13100": {  # 3-way with draw — not the 2-way moneyline
                        "bookmakerMarketId": "line/3/246/x/3/mon",
                        "outcomes": {
                            "13100": _ml_outcome("home", "3.55"),
                            "13102": _ml_outcome("away", "4.26"),
                            "13101": _ml_outcome("draw", "1.763"),
                        },
                    },
                }
            }
        },
    }


async def test_oddspapi_fetch_quotes_finds_moneyline() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        assert request.url.path.endswith("/odds")
        return httpx.Response(200, json=_odds_payload())

    provider = OddsPapiProvider(api_key="secret", transport=httpx.MockTransport(handler))
    quotes = await provider.fetch_quotes("fix-1", "13", ["pinnacle"])
    await provider.aclose()

    assert captured["apiKey"] == "secret"
    assert captured["bookmakers"] == "pinnacle"
    # Only the 2-way home/away moneyline (market 131), not the spread or 3-way.
    assert {q.outcome for q in quotes} == {"home", "away"}
    home = next(q for q in quotes if q.outcome == "home")
    assert home.market == "moneyline"
    assert home.decimal_odds == Decimal("1.763")
    assert abs(float(home.implied_prob) - 1 / 1.763) < 1e-9
    assert home.start_time == datetime(2026, 7, 21, 22, 40, tzinfo=UTC)
    assert home.raw is not None


async def test_oddspapi_no_moneyline_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"bookmakerOdds": {"pinnacle": {"markets": {
                "1366": {"bookmakerMarketId": "x/spreads", "outcomes": {
                    "1366": _ml_outcome("-2.0/home", "3.06"),
                    "1367": _ml_outcome("-2.0/away", "1.404"),
                }},
            }}}},
        )

    provider = OddsPapiProvider(api_key="k", transport=httpx.MockTransport(handler))
    quotes = await provider.fetch_quotes("f", "13", ["pinnacle"])
    await provider.aclose()
    assert quotes == []


async def test_oddspapi_retries_once_on_429() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": {"retryMs": 10}})
        return httpx.Response(200, json=_odds_payload())

    provider = OddsPapiProvider(api_key="k", transport=httpx.MockTransport(handler))
    quotes = await provider.fetch_quotes("f", "13", ["pinnacle"])
    await provider.aclose()
    assert calls["n"] == 2 and len(quotes) == 2


async def test_oddspapi_list_fixtures_mlb() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/fixtures")
        return httpx.Response(200, json={"fixtures": [
            {
                "fixtureId": "id123", "startTime": "2026-07-21T23:05:00.000Z",
                "participant1Abbr": "NYY", "participant1Name": "New York Yankees",
                "participant2Abbr": "PIT", "participant2Name": "Pittsburgh Pirates",
                "tournamentName": "MLB", "hasOdds": True,
                "externalProviders": {"pinnacleId": 1632524835},
            },
            {"id": "id456", "tournamentName": "NPB", "externalProviders": {}},
        ]})

    provider = OddsPapiProvider(api_key="k", transport=httpx.MockTransport(handler))
    fixtures = await provider.list_fixtures("13", datetime.now(UTC), datetime.now(UTC))
    await provider.aclose()
    assert [f.fixture_id for f in fixtures] == ["id123", "id456"]
    nyy = fixtures[0]
    assert nyy.tournament == "MLB" and nyy.p1_abbr == "NYY" and nyy.p2_abbr == "PIT"
    assert nyy.has_odds is True and nyy.pinnacle_id == "1632524835"
