"""Engine-side telemetry writers (Doc 3 §3.8, §3.9, §5).

The Trading Engine will use these; the demo session generator uses them now so
the monitor is exercised against the real write path, not a bespoke fixture.

- ``EventLog`` appends JSONL, fsync'd, so the monitor's tail and BACKTEST replay
  both see a durable, ordered stream.
- ``StatusWriter`` writes the status snapshot via temp-file + fsync + atomic
  rename, so a reader (monitor / Control CLI) never observes a torn file — the
  §5 hardening, applied to the status file too.
"""

from __future__ import annotations

import os
from pathlib import Path

from thorp.telemetry.events import EngineStatus, Event


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115

    def append(self, event: Event) -> None:
        self._file.write(event.model_dump_json() + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        self._file.close()


class StatusWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, status: EngineStatus) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(status.to_json())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # atomic rename
