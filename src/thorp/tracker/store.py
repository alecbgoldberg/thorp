"""Persist and load tracker observations (JSONL, one file per day)."""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from thorp.tracker.models import Observation

_ADAPTER: TypeAdapter[Observation] = TypeAdapter(Observation)


class ObservationStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "tracker" / "observations"
        self._dir.mkdir(parents=True, exist_ok=True)

    def append(self, obs: Observation) -> None:
        path = self._dir / f"date={obs.ts:%Y-%m-%d}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(obs.model_dump_json() + "\n")

    def load(self, game_key: str | None = None) -> list[Observation]:
        out: list[Observation] = []
        for path in sorted(self._dir.glob("date=*.jsonl")):
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                obs = _ADAPTER.validate_json(line)
                if game_key is None or obs.game_key == game_key:
                    out.append(obs)
        return out
