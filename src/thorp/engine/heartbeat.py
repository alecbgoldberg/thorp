"""Engine heartbeat (Doc 3 §5, Doc 4 §8).

Written **as the last step of each completed core-loop iteration** (not a free
timer) so a stuck loop stops producing heartbeats — the Watchdog's 10s threshold
then actually means "the loop is stuck", not just "the process is alive"
(the Opus gap-1 fix). Atomic write (temp + fsync + rename) so a reader never sees
a torn file. For prod this file should live on a small volume separate from the
bulk event log (Doc 3 §5); noted for when a live venue exists.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path


class HeartbeatWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def beat(self, now: datetime | None = None) -> None:
        stamp = (now or datetime.now(UTC)).isoformat()
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(stamp)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)


class HeartbeatReader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def last_beat(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self._path.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    def age_s(self, now: datetime | None = None) -> float:
        last = self.last_beat()
        if last is None:
            return float("inf")
        return ((now or datetime.now(UTC)) - last).total_seconds()
