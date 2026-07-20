"""Per-stream sequence-number monotonicity tracking (Doc 5 §6)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GapInfo:
    expected: int
    received: int

    @property
    def size(self) -> int:
        """Missed message count; negative means duplicate/out-of-order."""
        return self.received - self.expected


@dataclass
class SeqTracker:
    """Tracks last-seen seq per stream key (Kalshi: per subscription sid).

    ``observe`` returns a ``GapInfo`` when the incoming seq is not exactly
    ``last + 1``. The first observation on a key with no baseline is accepted
    silently — a baseline is normally set by ``reset`` when a snapshot arrives.
    """

    _last: dict[int, int] = field(default_factory=dict)

    def reset(self, key: int, seq: int) -> None:
        self._last[key] = seq

    def observe(self, key: int, seq: int) -> GapInfo | None:
        last = self._last.get(key)
        self._last[key] = seq
        if last is None or seq == last + 1:
            return None
        return GapInfo(expected=last + 1, received=seq)

    def last_seen(self, key: int) -> int | None:
        return self._last.get(key)
