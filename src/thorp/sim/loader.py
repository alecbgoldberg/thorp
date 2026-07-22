"""Load the collector's time series into per-game sim ticks."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from thorp.sim.core import BookTick, KalshiTick, Level


def _safe(game_key: str) -> str:
    return game_key.replace(":", "_").replace("/", "_")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def list_games(root: Path) -> list[str]:
    ts_root = root / "timeseries"
    keys: set[str] = set()
    for venue_dir in ts_root.glob("*"):
        for snap in venue_dir.glob("date=*/game=*/snapshots.jsonl"):
            recs = _read_jsonl(snap)
            if recs:
                keys.add(str(recs[0].get("game_key")))
    return sorted(keys)


def _ts(rec: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(rec["ts"]).replace("Z", "+00:00"))


def load_game(
    root: Path, game_key: str
) -> tuple[list[BookTick], list[KalshiTick], tuple[str, str] | None]:
    ts_root = root / "timeseries"
    safe = _safe(game_key)
    book_ticks: list[BookTick] = []
    kalshi_ticks: list[KalshiTick] = []
    teams: tuple[str, str] | None = None

    for venue_dir in sorted(ts_root.glob("*")):
        venue = venue_dir.name
        for snap in venue_dir.glob(f"date=*/game={safe}/snapshots.jsonl"):
            for rec in _read_jsonl(snap):
                if venue == "kalshi":
                    mid: dict[str, float | None] = {}
                    no_levels: dict[str, list[Level]] = {}
                    for m in rec.get("markets", []):
                        team = str(m["team"])
                        mid[team] = _opt_float(m.get("mid"))
                        no_levels[team] = [
                            (float(p), float(s)) for p, s in (m.get("no_levels") or [])
                        ]
                    kalshi_ticks.append(KalshiTick(ts=_ts(rec), mid=mid, no_levels=no_levels))
                else:
                    ht, at = str(rec["home_team"]), str(rec["away_team"])
                    if teams is None:
                        teams = (ht, at)
                    fair = {
                        ht: float(rec["home"]["prob_devig"]),
                        at: float(rec["away"]["prob_devig"]),
                    }
                    book_ticks.append(BookTick(ts=_ts(rec), venue=venue, fair=fair))

    book_ticks.sort(key=lambda t: t.ts)
    kalshi_ticks.sort(key=lambda t: t.ts)
    return book_ticks, kalshi_ticks, teams


def _opt_float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None
