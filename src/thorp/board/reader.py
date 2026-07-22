"""Read the latest snapshot per game from the collector's time series.

Reads ``data/timeseries/<venue>/date=…/game=…/snapshots.jsonl`` (what the
collector writes) and returns, per game, the most recent Pinnacle moneyline and
Kalshi book. Any non-``kalshi`` venue directory is treated as a book (a fair-
value source), so additional books slot in without code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GameSnapshots:
    game_key: str
    books: dict[str, dict[str, Any]] = field(default_factory=dict)  # venue -> latest book snapshot
    kalshi: dict[str, Any] | None = None


def _last_line(path: Path) -> dict[str, Any] | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    for chunk in reversed(data.split(b"\n")):
        chunk = chunk.strip()
        if chunk:
            try:
                obj: dict[str, Any] = json.loads(chunk)
                return obj
            except json.JSONDecodeError:
                continue
    return None


def read_latest(root: Path) -> list[GameSnapshots]:
    ts_root = root / "timeseries"
    games: dict[str, GameSnapshots] = {}
    if not ts_root.exists():
        return []
    for venue_dir in sorted(ts_root.iterdir()):
        if not venue_dir.is_dir():
            continue
        venue = venue_dir.name
        for game_dir in venue_dir.glob("date=*/game=*"):
            snap = _last_line(game_dir / "snapshots.jsonl")
            if snap is None:
                continue
            game_key = str(snap.get("game_key") or game_dir.name.replace("game=", ""))
            gs = games.setdefault(game_key, GameSnapshots(game_key=game_key))
            if venue == "kalshi":
                gs.kalshi = snap
            else:
                gs.books[venue] = snap
    return list(games.values())
