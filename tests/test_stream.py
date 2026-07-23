"""Live book maintenance from WS snapshot + deltas."""

from decimal import Decimal

from thorp.stream.book import LiveBook
from thorp.stream.kalshi_ws import KalshiBookStream


def test_snapshot_then_delta_bbo_and_ladder() -> None:
    b = LiveBook()
    b.apply_snapshot(
        yes_levels=[["0.40", "100"], ["0.41", "50"]],
        no_levels=[["0.55", "30"], ["0.58", "20"]],
    )
    # best yes bid 0.41; best no 0.58 -> yes ask 0.42; mid 0.415
    assert b.bbo() == (Decimal("0.41"), Decimal("0.42"), Decimal("0.415"))
    # a delta adds size and can create a new best
    b.apply_delta("yes", "0.43", "10")
    assert b.bbo()[0] == Decimal("0.43")
    # a negative delta that zeroes a level removes it
    b.apply_delta("yes", "0.43", "-10")
    assert Decimal("0.43") not in b.yes
    assert b.bbo()[0] == Decimal("0.41")


def test_delta_decrement_partial() -> None:
    b = LiveBook()
    b.apply_snapshot(yes_levels=[["0.40", "100"]], no_levels=[])
    b.apply_delta("yes", "0.40", "-40")
    assert b.yes[Decimal("0.40")] == Decimal("60")


def test_ladder_sorted_best_first() -> None:
    b = LiveBook()
    b.apply_snapshot(
        yes_levels=[["0.38", "10"], ["0.40", "20"], ["0.39", "30"]],
        no_levels=[["0.55", "5"]],
    )
    yes, no = b.ladder(top=2)
    assert yes == [(Decimal("0.40"), Decimal("20")), (Decimal("0.39"), Decimal("30"))]
    assert no == [(Decimal("0.55"), Decimal("5"))]


def test_stream_handles_snapshot_and_delta_messages() -> None:
    s = KalshiBookStream("wss://x/trade-api/ws/v2")
    s._handle('{"type":"orderbook_snapshot","sid":1,"seq":1,"msg":'
              '{"market_ticker":"KX-T","yes_dollars_fp":[["0.40","100"]],'
              '"no_dollars_fp":[["0.55","50"]]}}')
    assert s.book("KX-T") is not None
    assert s.bbo("KX-T")[0] == Decimal("0.40")
    s._handle('{"type":"orderbook_delta","sid":1,"seq":2,"msg":'
              '{"market_ticker":"KX-T","price_dollars":"0.41","delta_fp":"10","side":"yes"}}')
    assert s.bbo("KX-T")[0] == Decimal("0.41")


def test_stream_seq_gap_signals_resync() -> None:
    s = KalshiBookStream("wss://x/trade-api/ws/v2")
    s._handle('{"type":"orderbook_snapshot","sid":1,"seq":1,"msg":'
              '{"market_ticker":"KX-T","yes_dollars_fp":[["0.40","100"]],"no_dollars_fp":[]}}')
    # seq jumps 1 -> 5 (missed 2,3,4) -> resync
    result = s._handle('{"type":"orderbook_delta","sid":1,"seq":5,"msg":'
                       '{"market_ticker":"KX-T","price_dollars":"0.41","delta_fp":"10","side":"yes"}}')
    assert result == "resync"


def test_stream_subscribe_and_book_lookup() -> None:
    s = KalshiBookStream("wss://x/trade-api/ws/v2")
    s.subscribe(["KX-A", "KX-B"])
    assert s.book("KX-A") is None  # not populated until a snapshot arrives
    assert s.age_s("KX-A") == float("inf")
    assert s.ladder("KX-A") == ([], [])
