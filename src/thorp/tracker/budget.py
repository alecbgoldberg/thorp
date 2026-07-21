"""Persistent monthly OddsPapi call budget (the 250/mo free-tier cap).

A hard guard so the tracker can never blow the quota: usage is counted per
calendar month (UTC) in a small JSON file that survives restarts. Every OddsPapi
request goes through ``try_spend`` first; when the month's budget is exhausted it
returns False and the caller skips the call (Kalshi sampling continues freely).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("thorp.tracker")


class OddsBudget:
    def __init__(self, path: Path, monthly_limit: int = 250) -> None:
        self._path = path
        self._limit = monthly_limit
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, int] = self._load()

    @staticmethod
    def _month() -> str:
        return datetime.now(UTC).strftime("%Y-%m")

    def _load(self) -> dict[str, int]:
        try:
            raw = json.loads(self._path.read_text())
            return {str(k): int(v) for k, v in raw.items()}
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data))
        tmp.replace(self._path)

    def used(self) -> int:
        return self._data.get(self._month(), 0)

    def remaining(self) -> int:
        return max(0, self._limit - self.used())

    def try_spend(self, n: int = 1) -> bool:
        """Reserve ``n`` calls if the month's budget allows. Returns success."""
        month = self._month()
        used = self._data.get(month, 0)
        if used + n > self._limit:
            logger.warning(
                "OddsPapi monthly budget reached (%d/%d used this month) — skipping call",
                used,
                self._limit,
            )
            return False
        self._data[month] = used + n
        self._save()
        return True
