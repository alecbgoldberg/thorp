"""Monotonic-corrected wall-clock mapping (Doc 5 §4).

``receive_ts``/``process_ts`` must come from a clock that cannot go backwards or
jump mid-session: a system clock step (NTP correction, DST, VM pause) must never
make an interval measurement negative or wildly wrong. This maps
``time.monotonic_ns()`` onto wall time anchored at construction, re-synced
explicitly (and observably) via ``resync()``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

_NS_PER_S = 1_000_000_000


class CaptureClock:
    """Wall-clock timestamps driven by the monotonic clock between resyncs.

    ``now()`` advances strictly with the monotonic clock, so it is immune to
    system-clock steps. ``resync()`` re-anchors against NTP-disciplined system
    time and returns the drift it corrected, so drift is a logged, measurable
    quantity instead of silent skew.
    """

    def __init__(
        self,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._monotonic_ns = monotonic_ns
        self._wall_ns = wall_ns
        self._anchor_mono_ns = monotonic_ns()
        self._anchor_wall_ns = wall_ns()

    def now(self) -> datetime:
        mapped_ns = self._anchor_wall_ns + (self._monotonic_ns() - self._anchor_mono_ns)
        return _ns_to_datetime(mapped_ns)

    def resync(self) -> float:
        """Re-anchor to system wall time. Returns corrected drift in seconds.

        Positive drift means the mapped clock was ahead of system time.
        """
        mono = self._monotonic_ns()
        wall = self._wall_ns()
        mapped = self._anchor_wall_ns + (mono - self._anchor_mono_ns)
        self._anchor_mono_ns = mono
        self._anchor_wall_ns = wall
        return (mapped - wall) / _NS_PER_S


def _ns_to_datetime(ns: int) -> datetime:
    # Two-step conversion keeps microsecond precision; a single float division
    # of a current-epoch ns value would lose it to float64 rounding.
    base = datetime.fromtimestamp(ns // _NS_PER_S, tz=UTC)
    return base + timedelta(microseconds=(ns % _NS_PER_S) / 1_000)
