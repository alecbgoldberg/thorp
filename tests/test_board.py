"""Aggregation board: latest-snapshot reader, edge model, and the endpoint."""

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from thorp.board.model import build_board
from thorp.board.reader import GameSnapshots, read_latest
from thorp.board.server import BoardSource, build_server


def _write(root: Path, venue: str, game_key: str, lines: list[dict]) -> None:
    d = root / "timeseries" / venue / "date=2026-07-21" / f"game={game_key.replace(':', '_')}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "snapshots.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def _pin(prob_home: float, prob_away: float, ts: str) -> dict:
    return {
        "ts": ts, "game_key": "2026-07-21:COL-WSH", "matchup_id": 1,
        "home_team": "COL", "away_team": "WSH",
        "home": {"american": 102, "decimal_odds": "2.0", "prob_vig": "0.5",
                 "prob_devig": str(prob_home)},
        "away": {"american": -110, "decimal_odds": "1.9", "prob_vig": "0.52",
                 "prob_devig": str(prob_away)},
    }


def _kalshi(col_mid: float, wsh_mid: float, ts: str) -> dict:
    return {
        "ts": ts, "game_key": "2026-07-21:COL-WSH", "event_ticker": "E",
        "markets": [
            {"team": "COL", "ticker": "t1", "yes_bid": str(col_mid - 0.005),
             "yes_ask": str(col_mid + 0.005), "mid": str(col_mid), "last": str(col_mid),
             "volume": 1000000.0, "open_interest": 500000.0,
             "yes_levels": [["0.48", "1000"]], "no_levels": [["0.51", "2000"]]},
            {"team": "WSH", "ticker": "t2", "yes_bid": str(wsh_mid - 0.005),
             "yes_ask": str(wsh_mid + 0.005), "mid": str(wsh_mid), "last": str(wsh_mid),
             "volume": 900000.0, "open_interest": 400000.0, "yes_levels": [], "no_levels": []},
        ],
    }


def test_read_latest_takes_last_snapshot(tmp_path: Path) -> None:
    _write(tmp_path, "pinnacle", "2026-07-21:COL-WSH",
           [_pin(0.48, 0.52, "2026-07-21T23:00:00Z"), _pin(0.49, 0.51, "2026-07-21T23:00:05Z")])
    _write(tmp_path, "kalshi", "2026-07-21:COL-WSH", [_kalshi(0.49, 0.50, "2026-07-21T23:00:05Z")])
    games = read_latest(tmp_path)
    assert len(games) == 1
    g = games[0]
    assert g.books["pinnacle"]["home"]["prob_devig"] == "0.49"  # last line, not first
    assert g.kalshi is not None


def test_build_board_computes_edge_and_sorts() -> None:
    now = datetime(2026, 7, 21, 23, 0, 10, tzinfo=UTC)
    gs = GameSnapshots(game_key="2026-07-21:COL-WSH")
    gs.books["pinnacle"] = _pin(0.486, 0.514, "2026-07-21T23:00:05Z")
    gs.kalshi = _kalshi(0.45, 0.50, "2026-07-21T23:00:05Z")
    board = build_board([gs], now=now)
    row = board["games"][0]
    col = next(t for t in row["teams"] if t["team"] == "COL")
    # edge = consensus fair (0.486) - kalshi mid (0.45) = +0.036 -> Kalshi cheap
    assert abs(col["edge"] - 0.036) < 1e-6
    assert col["consensus"] == 0.486
    assert row["best_abs_edge"] >= 0.036
    assert col["yes_levels"] == [[0.48, 1000.0]]


def test_build_board_handles_missing_kalshi() -> None:
    gs = GameSnapshots(game_key="g")
    gs.books["pinnacle"] = _pin(0.5, 0.5, "2026-07-21T23:00:05Z")
    board = build_board([gs])
    row = board["games"][0]
    assert row["has_kalshi"] is False
    assert row["teams"][0]["edge"] is None


def test_board_endpoint_serves(tmp_path: Path) -> None:
    _write(tmp_path, "pinnacle", "2026-07-21:COL-WSH", [_pin(0.49, 0.51, "2026-07-21T23:00:05Z")])
    _write(tmp_path, "kalshi", "2026-07-21:COL-WSH", [_kalshi(0.45, 0.50, "2026-07-21T23:00:05Z")])
    server = build_server("127.0.0.1", 0, BoardSource(tmp_path))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        assert "THORP" in httpx.get(f"http://127.0.0.1:{port}/").text
        board = httpx.get(f"http://127.0.0.1:{port}/api/board").json()
        assert board["games"][0]["game_key"] == "2026-07-21:COL-WSH"
    finally:
        server.shutdown()
        thread.join(timeout=2)
