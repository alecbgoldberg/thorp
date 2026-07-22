"""Accounting, shadow fills, and the live-sim trade cycle end to end."""

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from thorp.common.clock import CaptureClock
from thorp.engine.accounting import PositionAccounting
from thorp.engine.live_sim import LiveSimEngine
from thorp.engine.shadow import ShadowVenue, kalshi_fee
from thorp.engine.types import ApprovedIntent, OrderIntent


def test_accounting_realized_unrealized_fees() -> None:
    a = PositionAccounting()
    a.apply_fill("M", "G", "buy_yes", Decimal("0.40"), 10, Decimal("0.05"))
    a.apply_fill("M", "G", "buy_yes", Decimal("0.50"), 10, Decimal("0.05"))
    assert a.positions["M"].net == 20 and a.positions["M"].avg == Decimal("0.45")
    a.apply_fill("M", "G", "sell_yes", Decimal("0.60"), 20, Decimal("0.10"))
    assert a.positions["M"].net == 0
    assert a.realized() == Decimal("3.00")  # 20 * (0.60 - 0.45)
    assert a.fees_paid == Decimal("0.20")


def test_accounting_unrealized_marks_to_mid() -> None:
    a = PositionAccounting()
    a.apply_fill("M", "G", "buy_yes", Decimal("0.40"), 10, Decimal("0"))
    assert a.unrealized({"M": Decimal("0.55")}) == Decimal("1.50")


def _intent(price: str, size: int) -> OrderIntent:
    return OrderIntent("s", "M", "G", "buy_yes", Decimal(price), size, "r", "i1")


def test_shadow_fill_walks_ladder_with_fee() -> None:
    venue = ShadowVenue()
    # no_levels (buy-NO bids): best 0.60 -> YES ask 0.40; 0.59 -> 0.41
    fill = venue.fill(ApprovedIntent(_intent("0.42", 120), 120),
                      yes_levels=[], no_levels=[(Decimal("0.60"), Decimal("50")),
                                                (Decimal("0.59"), Decimal("100"))])
    assert fill is not None and fill.size == 120
    assert abs(float(fill.price) - (50 * 0.40 + 70 * 0.41) / 120) < 1e-9
    assert fill.fee == kalshi_fee(fill.price, 120)


def test_shadow_no_fill_when_ask_above_limit() -> None:
    venue = ShadowVenue()
    # YES ask 0.40 (= 1 - 0.60) is above the 0.35 limit -> no fill.
    fill = venue.fill(ApprovedIntent(_intent("0.35", 100), 100),
                      yes_levels=[], no_levels=[(Decimal("0.60"), Decimal("50"))])
    assert fill is None


def _seed(root: Path) -> None:
    pin_dir = root / "timeseries" / "pinnacle" / "date=2026-07-22" / "game=2026-07-22_COL-WSH"
    kal_dir = root / "timeseries" / "kalshi" / "date=2026-07-22" / "game=2026-07-22_COL-WSH"
    pin_dir.mkdir(parents=True)
    kal_dir.mkdir(parents=True)
    (pin_dir / "snapshots.jsonl").write_text(json.dumps({
        "record_type": "pinnacle_snapshot", "ts": "2026-07-22T23:00:00Z",
        "game_key": "2026-07-22:COL-WSH", "matchup_id": 1, "home_team": "COL", "away_team": "WSH",
        "home": {"american": 100, "decimal_odds": "2.0", "prob_vig": "0.55", "prob_devig": "0.60"},
        "away": {"american": -110, "decimal_odds": "1.9", "prob_vig": "0.5", "prob_devig": "0.40"},
    }) + "\n")
    (kal_dir / "snapshots.jsonl").write_text(json.dumps({
        "record_type": "kalshi_snapshot", "ts": "2026-07-22T23:00:00Z",
        "game_key": "2026-07-22:COL-WSH", "event_ticker": "E", "markets": [
            {"team": "COL", "ticker": "KX-COL", "yes_bid": "0.49", "yes_ask": "0.50",
             "mid": "0.495", "last": "0.50", "volume": 1000.0, "open_interest": 500.0,
             "yes_levels": [["0.49", "500"]], "no_levels": [["0.50", "500"]]},
        ],
    }) + "\n")


def test_live_sim_trade_cycle_takes_edge_and_writes_status(tmp_path: Path) -> None:
    _seed(tmp_path)
    engine = LiveSimEngine(MagicMock(), tmp_path, CaptureClock())
    # COL: blended fair 0.60 vs Kalshi ask 0.50 -> 10c edge -> take buy_yes.
    engine.trade_cycle()
    engine.close()
    assert engine._acct.positions.get("KX-COL") is not None
    assert engine._acct.positions["KX-COL"].net > 0  # bought YES
    assert engine._acct.fees_paid > 0
    status = json.loads((tmp_path / "live" / "status.json").read_text())
    assert status["mode"] == "SIMULATION"
    assert any(p["market_key"] == "KX-COL" for p in status["positions"])
    events = (tmp_path / "live" / "events.jsonl").read_text().splitlines()
    assert any(json.loads(e).get("event_type") == "fill" for e in events)
