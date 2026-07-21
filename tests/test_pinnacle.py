"""Pinnacle scraper: American-odds conversion, game + moneyline normalization."""

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from thorp.odds.pinnacle import (
    PinnacleScraper,
    american_to_decimal,
    moneyline_from_rows,
)


def test_american_to_decimal() -> None:
    assert american_to_decimal(100) == Decimal(2)
    assert american_to_decimal(105) == Decimal("2.05")
    assert american_to_decimal(-110) == Decimal(1) + Decimal(100) / 110
    # -114 favorite -> ~1.877
    assert abs(float(american_to_decimal(-114)) - 1.877) < 1e-3


def test_moneyline_from_rows_picks_full_game_two_way() -> None:
    rows = [
        {"matchupId": 1, "type": "spread", "period": 0,
         "prices": [{"designation": "home", "price": -120}, {"designation": "away", "price": 100}]},
        {"matchupId": 1, "type": "moneyline", "period": 1,  # not full game
         "prices": [{"designation": "home", "price": -130}, {"designation": "away", "price": 110}]},
        {"matchupId": 1, "type": "moneyline", "period": 0,
         "prices": [{"designation": "home", "price": -114}, {"designation": "away", "price": 105}],
         "limits": [{"type": "maxRiskStake", "amount": 10000}], "cutoffAt": "2026-07-22T00:40:00Z"},
        {"matchupId": 2, "type": "moneyline", "period": 0,
         "prices": [{"designation": "home", "price": -200}, {"designation": "away", "price": 170}]},
    ]
    ml = moneyline_from_rows(rows, 1)
    assert ml is not None
    assert ml["home"]["american"] == -114
    assert ml["away"]["american"] == 105
    assert ml["home"]["decimal"] == american_to_decimal(-114)
    assert abs(float(ml["home"]["prob_vig"]) - 1 / float(american_to_decimal(-114))) < 1e-9
    assert ml["home"]["max_stake"] == 10000


def test_moneyline_from_rows_absent_returns_none() -> None:
    rows = [{"matchupId": 1, "type": "spread", "period": 0, "prices": []}]
    assert moneyline_from_rows(rows, 1) is None
    assert moneyline_from_rows([], 1) is None


def _matchups_payload() -> list[dict]:
    return [
        {"id": 100, "parentId": None, "startTime": "2026-07-22T01:40:00Z",
         "participants": [{"name": "Seattle Mariners", "alignment": "home"},
                          {"name": "Cincinnati Reds", "alignment": "away"}]},
        {"id": 101, "parentId": 50,  # sub-market, ignored
         "participants": [{"name": "A", "alignment": "home"}, {"name": "B", "alignment": "away"}]},
        {"id": 102, "parentId": None,  # only one participant, ignored
         "participants": [{"name": "X", "alignment": "home"}]},
    ]


async def test_list_games_filters_real_games() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/leagues/246/matchups")
        assert request.headers["x-api-key"]  # public frontend key sent
        return httpx.Response(200, json=_matchups_payload())

    scraper = PinnacleScraper(min_interval_s=0.0, transport=httpx.MockTransport(handler))
    games = await scraper.list_games("246")
    await scraper.aclose()
    assert len(games) == 1
    g = games[0]
    assert g.matchup_id == 100
    assert g.home_name == "Seattle Mariners" and g.away_name == "Cincinnati Reds"
    assert g.start_time == datetime(2026, 7, 22, 1, 40, tzinfo=UTC)


async def test_fetch_quotes_returns_moneyline_home_away() -> None:
    rows = [
        {"matchupId": 100, "type": "moneyline", "period": 0,
         "prices": [{"designation": "home", "price": -114}, {"designation": "away", "price": 105}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/matchups/100/markets/related/straight" in request.url.path
        return httpx.Response(200, json=rows)

    scraper = PinnacleScraper(min_interval_s=0.0, transport=httpx.MockTransport(handler))
    quotes = await scraper.fetch_quotes("100", "246", ["pinnacle"])
    await scraper.aclose()
    assert {q.outcome for q in quotes} == {"home", "away"}
    home = next(q for q in quotes if q.outcome == "home")
    assert home.bookmaker == "pinnacle" and home.decimal_odds == american_to_decimal(-114)


async def test_scraper_retries_on_429() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=[])

    scraper = PinnacleScraper(min_interval_s=0.0, transport=httpx.MockTransport(handler))
    # patch the backoff sleep to be instant via min_interval already 0; 429 sleeps 2s,
    # so override by calling straight_markets and asserting it eventually succeeds.
    import thorp.odds.pinnacle as pin

    orig = pin.asyncio.sleep

    async def fast_sleep(_: float) -> None:
        await orig(0)

    pin.asyncio.sleep = fast_sleep  # type: ignore[assignment]
    try:
        rows = await scraper.straight_markets("246")
    finally:
        pin.asyncio.sleep = orig  # type: ignore[assignment]
        await scraper.aclose()
    assert calls["n"] == 2 and rows == []
