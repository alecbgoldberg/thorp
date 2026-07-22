"""ESPN odds source: scoreboard moneyline parsing."""

from datetime import UTC, datetime

import httpx

from thorp.odds.espn import EspnScraper, parse_scoreboard


def _event(home: str, away: str, home_ml: str, away_ml: str) -> dict:
    return {
        "date": "2026-07-22T22:40Z",
        "competitions": [{
            "date": "2026-07-22T22:40Z",
            "competitors": [
                {"homeAway": "home", "team": {"abbreviation": home}},
                {"homeAway": "away", "team": {"abbreviation": away}},
            ],
            "odds": [{
                "provider": {"name": "DraftKings"},
                "moneyline": {
                    "home": {"close": {"odds": home_ml}},
                    "away": {"close": {"odds": away_ml}},
                },
            }],
        }],
    }


def test_parse_scoreboard_extracts_moneylines() -> None:
    payload = {"events": [_event("NYY", "PIT", "-167", "+138")]}
    games = parse_scoreboard(payload)
    assert len(games) == 1
    g = games[0]
    assert g.home_abbr == "NYY" and g.away_abbr == "PIT"
    assert g.home_american == -167 and g.away_american == 138
    assert g.provider == "DraftKings"
    assert g.start_time == datetime(2026, 7, 22, 22, 40, tzinfo=UTC)


def test_parse_scoreboard_skips_events_without_odds() -> None:
    ev = _event("NYY", "PIT", "-167", "+138")
    ev["competitions"][0]["odds"] = []
    assert parse_scoreboard({"events": [ev]}) == []


async def test_scoreboard_client_hits_dates_param() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        assert request.url.path.endswith("/baseball/mlb/scoreboard")
        return httpx.Response(200, json={"events": [_event("LAD", "PHI", "-150", "+130")]})

    scraper = EspnScraper(min_interval_s=0.0, transport=httpx.MockTransport(handler))
    games = await scraper.scoreboard("20260722")
    await scraper.aclose()
    assert seen["dates"] == "20260722"
    assert games[0].home_abbr == "LAD" and games[0].home_american == -150
