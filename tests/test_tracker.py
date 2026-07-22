"""MLB tracker: teams, Kalshi parsing, matching, budget, store, analysis."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from thorp.odds.types import Fixture
from thorp.tracker.analyze import analyze_game
from thorp.tracker.budget import OddsBudget
from thorp.tracker.kalshi_mlb import (
    KalshiMlbClient,
    orderbook_mid,
    parse_event_date,
    team_from_ticker,
)
from thorp.tracker.matching import match_games, resolve_ref_prob
from thorp.tracker.models import KalshiGame, Observation
from thorp.tracker.store import ObservationStore
from thorp.tracker.teams_mlb import canon


# ------------------------------------------------------------------- teams
def test_canon_across_sources() -> None:
    assert canon("KC") == canon("Kansas City") == canon("Kansas City Royals") == "KC"
    assert canon("TB") == canon("Tampa Bay Rays") == "TB"
    assert canon("Oakland Athletics") == canon("ATH") == "ATH"


def test_canon_ambiguous_city_is_none() -> None:
    # Bare ambiguous cities must not resolve — disambiguate by abbr/nickname.
    assert canon("New York") is None
    assert canon("Chicago") is None
    assert canon("Yankees") == "NYY" and canon("Mets") == "NYM"


def test_canon_unknown_is_none() -> None:
    assert canon("Nowhere FC") is None
    assert canon("") is None


# ------------------------------------------------------------- kalshi parsing
def test_parse_event_date_and_team() -> None:
    assert parse_event_date("KXMLBGAME-26JUL231840KCDET") == date(2026, 7, 23)
    assert parse_event_date("garbage") is None
    assert team_from_ticker("KXMLBGAME-26JUL231840KCDET-DET") == "DET"


def test_orderbook_mid_new_schema() -> None:
    # orderbook_fp with dollar-string prices/sizes (elections host).
    payload = {"orderbook_fp": {
        "yes_dollars": [["0.40", "10"], ["0.41", "5"]],
        "no_dollars": [["0.55", "3"], ["0.58", "2"]],
    }}
    # best yes bid 0.41; best no 0.58 -> yes ask 0.42; mid = 0.415
    assert orderbook_mid(payload) == Decimal("0.415")
    assert orderbook_mid({"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}) is None
    assert orderbook_mid({"orderbook_fp": {"yes_dollars": [["0.30", "1"]]}}) == Decimal("0.30")


def test_orderbook_levels_best_first() -> None:
    from thorp.tracker.kalshi_mlb import orderbook_levels

    payload = {"orderbook_fp": {
        "yes_dollars": [["0.09", "50222"], ["0.11", "98441"], ["0.10", "60557"]],
        "no_dollars": [["0.82", "25074"]],
    }}
    yes, no = orderbook_levels(payload, top=2)
    assert yes == [(Decimal("0.11"), Decimal("98441")), (Decimal("0.10"), Decimal("60557"))]
    assert no == [(Decimal("0.82"), Decimal("25074"))]


def test_market_quote_dollar_fp_fields() -> None:
    from thorp.tracker.kalshi_mlb import market_quote

    q = market_quote({
        "yes_bid_dollars": "0.14", "yes_ask_dollars": "0.15",
        "last_price_dollars": "0.15", "volume_fp": "1861485.85",
        "open_interest_fp": "1273123.57",
    })
    assert q.yes_bid == Decimal("0.14") and q.yes_ask == Decimal("0.15")
    assert q.mid == Decimal("0.145") and q.last == Decimal("0.15")
    assert q.volume == 1861485.85 and q.open_interest == 1273123.57
    # untraded market -> all None
    empty = market_quote({})
    assert empty.mid is None and empty.volume is None


class FakeRest:
    def __init__(self, markets: list[dict], books: dict[str, dict]) -> None:
        self._markets = markets
        self._books = books

    async def get_open_markets(self, series: str) -> list[dict]:
        return self._markets

    async def get_orderbook(self, ticker: str) -> dict:
        return self._books[ticker]


async def test_kalshi_list_games_groups_by_event() -> None:
    markets = [
        {"ticker": "KXMLBGAME-26JUL231840KCDET-KC", "event_ticker": "KXMLBGAME-26JUL231840KCDET",
         "yes_sub_title": "Kansas City"},
        {"ticker": "KXMLBGAME-26JUL231840KCDET-DET", "event_ticker": "KXMLBGAME-26JUL231840KCDET",
         "yes_sub_title": "Detroit"},
        {"ticker": "KXMLBGAME-26JUL231507TBTOR-TB", "event_ticker": "KXMLBGAME-26JUL231507TBTOR",
         "yes_sub_title": "Tampa Bay"},  # only one side -> dropped
    ]
    client = KalshiMlbClient(FakeRest(markets, {}), "KXMLBGAME")  # type: ignore[arg-type]
    games = await client.list_games()
    assert set(games) == {"KXMLBGAME-26JUL231840KCDET"}
    game = games["KXMLBGAME-26JUL231840KCDET"]
    assert set(game.market_by_team) == {"KC", "DET"}
    assert game.game_date == date(2026, 7, 23)


# ----------------------------------------------------------------- matching
def _fixture(p1: str, p2: str, start: datetime, pinn: str | None = "123") -> Fixture:
    return Fixture(
        provider="oddspapi", fixture_id=f"fx-{p1}{p2}", sport="13", tournament="MLB",
        start_time=start, p1_abbr=p1, p2_abbr=p2, has_odds=True, pinnacle_id=pinn,
    )


def _kalshi_game() -> dict[str, KalshiGame]:
    return {"E": KalshiGame(
        event_ticker="KXMLBGAME-26JUL231840KCDET", game_date=date(2026, 7, 23),
        market_by_team={"KC": "tick-KC", "DET": "tick-DET"},
        name_by_team={"KC": "Kansas City", "DET": "Detroit"},
    )}


def test_match_games_pairs_by_teams_and_date() -> None:
    start = datetime(2026, 7, 23, 22, 40, tzinfo=UTC)
    fixtures = [
        _fixture("KC", "DET", start),
        _fixture("NYY", "PIT", start),  # unrelated
    ]
    links = match_games(_kalshi_game(), fixtures)
    assert len(links) == 1
    link = links[0]
    assert link.teams == ("DET", "KC") and link.ref_team == "DET"
    assert link.oddspapi_fixture_id == "fx-KCDET"
    assert link.start_time == start


def test_match_games_ignores_non_mlb_and_unmatched() -> None:
    start = datetime(2026, 7, 23, 22, 40, tzinfo=UTC)
    npb = Fixture(provider="oddspapi", fixture_id="x", sport="13", tournament="NPB",
                  start_time=start, p1_abbr="KC", p2_abbr="DET")
    assert match_games(_kalshi_game(), [npb]) == []


def test_resolve_ref_prob_locks_orientation() -> None:
    # Kalshi says ref_team ~0.58; home=0.60 is closest -> orientation home.
    prob, orient = resolve_ref_prob(0.60, 0.40, kalshi_ref_prob=0.58, locked=None)
    assert orient == "home" and prob == 0.60
    # Once locked to away, it stays away regardless of agreement.
    prob2, orient2 = resolve_ref_prob(0.60, 0.40, kalshi_ref_prob=0.58, locked="away")
    assert orient2 == "away" and prob2 == 0.40


# ------------------------------------------------------------------- budget
def test_budget_enforces_monthly_limit(tmp_path: Path) -> None:
    b = OddsBudget(tmp_path / "budget.json", monthly_limit=3)
    assert b.remaining() == 3
    assert b.try_spend(2) and b.remaining() == 1
    assert not b.try_spend(2)  # would exceed
    assert b.try_spend(1) and b.remaining() == 0
    assert not b.try_spend(1)


def test_budget_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    OddsBudget(path, 10).try_spend(4)
    assert OddsBudget(path, 10).used() == 4


# -------------------------------------------------------------- store + analyze
def _obs(game_key: str, source: str, ts: datetime, prob: float) -> Observation:
    return Observation(game_key=game_key, ref_team="DET", source=source,  # type: ignore[arg-type]
                       prob=Decimal(str(prob)), ts=ts)


def test_store_round_trip_and_filter(tmp_path: Path) -> None:
    store = ObservationStore(tmp_path)
    base = datetime(2026, 7, 23, 22, tzinfo=UTC)
    store.append(_obs("g1", "kalshi", base, 0.5))
    store.append(_obs("g2", "kalshi", base, 0.4))
    store.append(_obs("g1", "pinnacle", base, 0.52))
    assert len(store.load()) == 3
    assert len(store.load("g1")) == 2


def test_analyze_reports_insufficient_data(tmp_path: Path) -> None:
    base = datetime(2026, 7, 23, 22, tzinfo=UTC)
    obs = [_obs("g", "kalshi", base + timedelta(seconds=i), 0.5) for i in range(10)]
    ga = analyze_game("g", obs)  # no pinnacle points
    assert ga.result is None and "insufficient" in ga.note


def test_analyze_detects_pinnacle_lead() -> None:
    # Pinnacle series leads Kalshi by 60s: kalshi(t) = pinnacle(t - 60s).
    base = datetime(2026, 7, 23, 22, tzinfo=UTC)
    obs: list[Observation] = []
    seq = [0.50 + 0.002 * i for i in range(80)]  # steadily rising sharp prob
    for i in range(80):
        t = base + timedelta(seconds=30 * i)
        obs.append(_obs("g", "pinnacle", t, seq[i]))
        obs.append(_obs("g", "kalshi", t, seq[max(0, i - 2)]))  # lag 2 steps = 60s
    ga = analyze_game("g", obs, step_s=30.0, max_lag_s=300.0, min_points=8)
    assert ga.result is not None
    assert ga.result.sharp_leads is True
    assert ga.result.best_lag_s > 0
