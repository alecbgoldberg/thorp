"""Rich time-series snapshot storage (JSONL), partitioned for S3 + DuckDB.

    data/timeseries/<venue>/date=YYYY-MM-DD/game=<key>/snapshots.jsonl

One append-only file per venue/date/game. The layout mirrors Doc 5's partition
scheme so ``aws s3 sync data/timeseries s3://...`` and a DuckDB
``read_json_auto`` query both work without reshaping.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from thorp.collector.models import BookSnapshot, KalshiSnapshot, PinnacleSnapshot

Snapshot = KalshiSnapshot | PinnacleSnapshot | BookSnapshot


def _safe(game_key: str) -> str:
    return game_key.replace(":", "_").replace("/", "_")


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self._root = root / "timeseries"

    def _path(self, venue: str, game_key: str, ts: datetime) -> Path:
        return (
            self._root
            / venue
            / f"date={ts:%Y-%m-%d}"
            / f"game={_safe(game_key)}"
            / "snapshots.jsonl"
        )

    def append(self, venue: str, snapshot: Snapshot) -> None:
        path = self._path(venue, snapshot.game_key, snapshot.ts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(snapshot.model_dump_json() + "\n")

    def load_pinnacle(self, game_key: str, date_str: str) -> list[PinnacleSnapshot]:
        path = self._path("pinnacle", game_key, _date(date_str))
        adapter: TypeAdapter[PinnacleSnapshot] = TypeAdapter(PinnacleSnapshot)
        return _load(path, adapter)

    def load_kalshi(self, game_key: str, date_str: str) -> list[KalshiSnapshot]:
        path = self._path("kalshi", game_key, _date(date_str))
        adapter: TypeAdapter[KalshiSnapshot] = TypeAdapter(KalshiSnapshot)
        return _load(path, adapter)


def _date(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str)


def _load[T](path: Path, adapter: TypeAdapter[T]) -> list[T]:
    if not path.exists():
        return []
    out: list[T] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(adapter.validate_json(line))
    return out
