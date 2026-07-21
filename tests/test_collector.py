"""Collector: date-aware matching, ref-side, and snapshot storage."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from thorp.collector.collector import match
from thorp.collector.models import (
    CollectorGame,
    KalshiMarketBook,
    KalshiSnapshot,
    MoneylineSide,
    PinnacleSnapshot,
)
from thorp.collector.snapshots import SnapshotStore
from thorp.odds.pinnacle import PinnacleGame
from thorp.tracker.models import KalshiGame


def _kalshi_game(day: int) -> KalshiGame:
    return KalshiGame(
        event_ticker=f"KXMLBGAME-26JUL{day}2040WSHCOL",
        game_date=date(2026, 7, day),
        market_by_team={"COL": f"tick-{day}-COL", "WSH": f"tick-{day}-WSH"},
        name_by_team={"COL": "Colorado", "WSH": "Washington"},
    )


def _pin_game(mid: int, iso: str) -> PinnacleGame:
    # start UTC; evening ET games roll to the next UTC day.
    return PinnacleGame(
        matchup_id=mid,
        start_time=datetime.fromisoformat(iso),
        home_name="Colorado Rockies",
        away_name="Washington Nationals",
    )


def test_match_aligns_by_eastern_date() -> None:
    kalshi = {"21": _kalshi_game(21), "22": _kalshi_game(22)}
    # Pinnacle: the 21st ET game (00:40Z on 22nd) and the 22nd ET game.
    pinnacle = [
        _pin_game(1001, "2026-07-22T00:40:00+00:00"),  # ET date = 2026-07-21
        _pin_game(1002, "2026-07-23T00:40:00+00:00"),  # ET date = 2026-07-22
    ]
    links = match(kalshi, pinnacle)
    by_key = {link.game_key: link for link in links}
    assert by_key["2026-07-21:COL-WSH"].pinnacle_matchup_id == 1001
    assert by_key["2026-07-22:COL-WSH"].pinnacle_matchup_id == 1002


def test_match_skips_when_pinnacle_lacks_that_date() -> None:
    # Only the 21st Pinnacle game exists; the 22nd Kalshi game must NOT borrow it.
    kalshi = {"21": _kalshi_game(21), "22": _kalshi_game(22)}
    pinnacle = [_pin_game(1001, "2026-07-22T00:40:00+00:00")]
    links = match(kalshi, pinnacle)
    assert [link.game_key for link in links] == ["2026-07-21:COL-WSH"]


def test_match_sets_ref_side() -> None:
    kalshi = {"21": _kalshi_game(21)}
    pinnacle = [_pin_game(1001, "2026-07-22T00:40:00+00:00")]
    link = match(kalshi, pinnacle)[0]
    # ref_team = min(COL, WSH) = "COL", which is Pinnacle home -> ref_side "home".
    assert link.ref_team == "COL"
    assert link.pinnacle_ref_side == "home"
    assert link.teams == ("COL", "WSH")


def _side(american: int, dv: str) -> MoneylineSide:
    from thorp.odds.pinnacle import american_to_decimal

    dec = american_to_decimal(american)
    return MoneylineSide(american=american, decimal_odds=dec, prob_vig=Decimal(1) / dec,
                         prob_devig=Decimal(dv))


def test_snapshot_store_round_trip(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    ts = datetime(2026, 7, 21, 23, 0, tzinfo=UTC)
    store.append("pinnacle", PinnacleSnapshot(
        ts=ts, game_key="2026-07-21:COL-WSH", matchup_id=1001,
        home_team="COL", away_team="WSH",
        home=_side(102, "0.485"), away=_side(-110, "0.515"), max_stake=15000,
    ))
    store.append("kalshi", KalshiSnapshot(
        ts=ts, game_key="2026-07-21:COL-WSH", event_ticker="E",
        markets=[KalshiMarketBook(team="COL", ticker="t", yes_bid=Decimal("0.48"),
                                  yes_ask=Decimal("0.5"), mid=Decimal("0.49"))],
    ))
    # Partitioned path exists (S3-ready).
    p = tmp_path / "timeseries" / "pinnacle" / "date=2026-07-21" / "game=2026-07-21_COL-WSH"
    assert (p / "snapshots.jsonl").exists()

    pins = store.load_pinnacle("2026-07-21:COL-WSH", "2026-07-21")
    assert len(pins) == 1 and pins[0].max_stake == 15000
    assert pins[0].home.american == 102
    kals = store.load_kalshi("2026-07-21:COL-WSH", "2026-07-21")
    assert len(kals) == 1 and kals[0].markets[0].mid == Decimal("0.49")


def test_collector_game_model_frozen() -> None:
    link = CollectorGame(
        game_key="2026-07-21:COL-WSH", teams=("COL", "WSH"), ref_team="COL",
        kalshi_event="E", kalshi_market_by_team={"COL": "t1", "WSH": "t2"},
        pinnacle_matchup_id=1001, pinnacle_ref_side="home",
    )
    assert link.pinnacle_ref_side == "home"
