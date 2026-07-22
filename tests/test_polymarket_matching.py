"""Cross-venue event matcher: Kalshi <-> Polymarket US same-contract check."""

from datetime import date

from thorp.polymarket.matching import (
    EventOutcome,
    from_kalshi_ticker,
    from_polymarket_symbol,
    match_symbols,
    same_contract,
)


def test_from_kalshi_ticker() -> None:
    eo = from_kalshi_ticker("KXMLBGAME-26JUL231840KCDET-KC")
    assert eo == EventOutcome(sport="mlb", date=date(2026, 7, 23), outcome_team="KC")


def test_from_kalshi_ticker_bad() -> None:
    assert from_kalshi_ticker("NOTAGAME-XYZ") is None


def test_from_polymarket_symbol() -> None:
    # Documented format: tec-<sport>-<event...>-YYYY-MM-DD-<team>
    eo = from_polymarket_symbol("tec-mlb-kcdet-2026-07-23-kc")
    assert eo == EventOutcome(sport="mlb", date=date(2026, 7, 23), outcome_team="KC")
    # tolerant of a multi-segment event middle
    eo2 = from_polymarket_symbol("tec-mlb-royals-tigers-2026-07-23-kc")
    assert eo2 is not None and eo2.outcome_team == "KC"


def test_from_polymarket_symbol_bad() -> None:
    assert from_polymarket_symbol("garbage") is None
    assert from_polymarket_symbol("tec-mlb-2026-13-40-kc") is None  # bad date


def test_same_contract_true_and_false() -> None:
    k = from_kalshi_ticker("KXMLBGAME-26JUL231840KCDET-KC")
    p_same = from_polymarket_symbol("tec-mlb-kcdet-2026-07-23-kc")
    p_wrong_team = from_polymarket_symbol("tec-mlb-kcdet-2026-07-23-det")
    p_wrong_date = from_polymarket_symbol("tec-mlb-kcdet-2026-07-24-kc")
    assert same_contract(k, p_same)
    assert not same_contract(k, p_wrong_team)
    assert not same_contract(k, p_wrong_date)


def test_match_symbols_picks_the_same_contract() -> None:
    kalshi = "KXMLBGAME-26JUL231840KCDET-KC"
    symbols = [
        "tec-mlb-kcdet-2026-07-23-det",  # wrong outcome
        "tec-mlb-kcdet-2026-07-23-kc",  # match
        "tec-nba-bosmia-2026-07-23-bos",  # wrong sport
    ]
    link = match_symbols(kalshi, symbols)
    assert link is not None
    assert link.polymarket_symbol == "tec-mlb-kcdet-2026-07-23-kc"
    assert link.kalshi_ticker == kalshi
    assert link.outcome.outcome_team == "KC"


def test_match_symbols_none_when_absent() -> None:
    assert match_symbols("KXMLBGAME-26JUL231840KCDET-KC",
                         ["tec-mlb-kcdet-2026-07-24-kc"]) is None
