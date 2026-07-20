"""Append-only newline-delimited JSON journal, rotated hourly (Doc 5 §3).

Local-first for durability against network blips; the hourly Parquet
compaction job (Week 2) reads these files, verifies row counts, uploads to S3,
and only then deletes them. Directory layout mirrors the S3 partition scheme:

    <root>/<venue>/<data_type>/date=YYYY-MM-DD/HH.jsonl

Writes are line-buffered (flushed per record) and fsync'd at a bounded
interval, so a crash loses at most ``fsync_interval_s`` of buffered-at-the-OS
data and can leave at most one truncated final line, which the compaction
reader must tolerate (skip + log, never crash).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import IO

from thorp.common.clock import CaptureClock
from thorp.common.records import BaseRecord

logger = logging.getLogger(__name__)


class JournalWriter:
    def __init__(
        self,
        root: Path,
        venue: str,
        data_type: str,
        clock: CaptureClock,
        fsync_interval_s: float = 5.0,
    ) -> None:
        self._dir = root / venue / data_type
        self._clock = clock
        self._fsync_interval_s = fsync_interval_s
        self._file: IO[str] | None = None
        self._file_hour: tuple[int, int, int, int] | None = None  # (y, m, d, h) UTC
        self._last_fsync = clock.now()
        self.records_written = 0

    def write(self, record: BaseRecord) -> None:
        now = self._clock.now()
        f = self._file_for(now)
        f.write(record.to_json_line() + "\n")
        self.records_written += 1
        if (now - self._last_fsync).total_seconds() >= self._fsync_interval_s:
            os.fsync(f.fileno())
            self._last_fsync = now

    def close(self) -> None:
        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None
            self._file_hour = None

    def _file_for(self, now: datetime) -> IO[str]:
        hour = (now.year, now.month, now.day, now.hour)
        if self._file is None or self._file_hour != hour:
            self.close()
            path = self._dir / f"date={now:%Y-%m-%d}" / f"{now:%H}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            # Append mode: a restart within the same hour continues the file.
            self._file = open(path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
            self._file_hour = hour
            logger.info("journal opened %s", path)
        return self._file


class JournalSet:
    """Lazily-created writers keyed by (venue, data_type), one per stream."""

    def __init__(self, root: Path, clock: CaptureClock, fsync_interval_s: float = 5.0) -> None:
        self._root = root
        self._clock = clock
        self._fsync_interval_s = fsync_interval_s
        self._writers: dict[tuple[str, str], JournalWriter] = {}

    def write(self, venue: str, data_type: str, record: BaseRecord) -> None:
        key = (venue, data_type)
        writer = self._writers.get(key)
        if writer is None:
            writer = JournalWriter(
                self._root, venue, data_type, self._clock, self._fsync_interval_s
            )
            self._writers[key] = writer
        writer.write(record)

    def stats(self) -> dict[str, int]:
        return {f"{v}/{d}": w.records_written for (v, d), w in self._writers.items()}

    def close(self) -> None:
        for writer in self._writers.values():
            writer.close()
