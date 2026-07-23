"""Spread/total parsing + the careful Kalshi<->Pinnacle line matching."""

from decimal import Decimal

from thorp.collector.spread_total import (
    match_spreads,
    match_totals,
    parse_spread_market,
    parse_total_market,
    spread_event_ticker,
    total_event_ticker,
)
from thorp.odds.pinnacle import spreads_from_rows, totals_from_rows


def test_event_ticker_mapping() -> None:
    g = "KXMLBGAME-26JUL231840KCDET"
    assert spread_event_ticker(g) == "KXMLBSPREAD-26JUL231840KCDET"
    assert total_event_ticker(g) == "KXMLBTOTAL-26JUL231840KCDET"


def test_parse_kalshi_spread_and_total() -> None:
    assert parse_spread_market(
        {"ticker": "KXMLBSPREAD-26JUL221840LADPHI-LAD5", "floor_strike": 4.5}
    ) == ("LAD", 4.5)
    assert parse_total_market(
        {"ticker": "KXMLBTOTAL-26JUL221840MINCLE-18", "floor_strike": 17.5}
    ) == 17.5


def _pin_spread_rows(mid: int) -> list[dict]:
    return [{"matchupId": mid, "type": "spread", "period": 0, "prices": [
        {"designation": "home", "points": 1.5, "price": 150},
        {"designation": "away", "points": -1.5, "price": -170},
    ]}]


def _pin_total_rows(mid: int) -> list[dict]:
    return [{"matchupId": mid, "type": "total", "period": 0, "prices": [
        {"designation": "over", "points": 8.5, "price": -105},
        {"designation": "under", "points": 8.5, "price": -105},
    ]}]


def test_pinnacle_spread_devig_keyed_by_side_points() -> None:
    sp = spreads_from_rows(_pin_spread_rows(1), 1)
    # away -1.5 is the favorite; its de-vigged cover prob should exceed home +1.5
    assert sp[("away", -1.5)] > sp[("home", 1.5)]
    assert abs(sp[("home", 1.5)] + sp[("away", -1.5)] - 1.0) < 1e-6  # de-vigged, sums to 1


def test_pinnacle_totals_devig() -> None:
    tot = totals_from_rows(_pin_total_rows(1), 1)
    over, under = tot[8.5]
    assert abs(over + under - 1.0) < 1e-6
    assert abs(over - 0.5) < 0.02  # -105/-105 ~ pick'em


def test_match_spread_maps_kalshi_over_L_to_pinnacle_minus_L() -> None:
    # Kalshi "PHI wins by over 1.5" -> Pinnacle (away=PHI, -1.5). home=LAD away=PHI.
    pin = spreads_from_rows(_pin_spread_rows(1), 1)  # home LAD +1.5, away PHI -1.5
    kalshi = [{"ticker": "KXMLBSPREAD-x-PHI2", "floor_strike": 1.5,
               "yes_bid_dollars": "0.55", "yes_ask_dollars": "0.57"}]
    pairs = match_spreads(kalshi, pin, home_team="LAD", away_team="PHI")
    assert len(pairs) == 1
    p = pairs[0]
    assert p.selection == "PHI" and p.line == 1.5
    assert p.pinnacle_prob == pin[("away", -1.5)]  # matched the -1.5 side
    assert p.kalshi_prob == Decimal("0.56")  # mid of 0.55/0.57
    assert p.edge is not None


def test_match_spread_skips_line_with_no_pinnacle_counterpart() -> None:
    pin = spreads_from_rows(_pin_spread_rows(1), 1)  # only 1.5 exists
    kalshi = [{"ticker": "KXMLBSPREAD-x-PHI5", "floor_strike": 4.5,  # no Pinnacle 4.5
               "yes_bid_dollars": "0.10", "yes_ask_dollars": "0.12"}]
    assert match_spreads(kalshi, pin, "LAD", "PHI") == []


def test_match_total_over_line() -> None:
    tot = totals_from_rows(_pin_total_rows(1), 1)
    kalshi = [{"ticker": "KXMLBTOTAL-x-9", "floor_strike": 8.5,
               "yes_bid_dollars": "0.48", "yes_ask_dollars": "0.50"}]
    pairs = match_totals(kalshi, tot)
    assert len(pairs) == 1 and pairs[0].selection == "over" and pairs[0].line == 8.5
    assert pairs[0].pinnacle_prob == tot[8.5][0]
