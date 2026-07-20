"""CaptureClock: immune to wall-clock steps between resyncs (Doc 5 §4)."""

from datetime import timedelta

from thorp.common.clock import CaptureClock

NS = 1_000_000_000


class FakeTime:
    def __init__(self, wall_start_ns: int = 1_760_000_000 * NS) -> None:
        self.mono_ns = 5_000 * NS
        self.wall_ns = wall_start_ns

    def advance(self, seconds: float) -> None:
        self.mono_ns += int(seconds * NS)
        self.wall_ns += int(seconds * NS)

    def jump_wall(self, seconds: float) -> None:
        """A system clock step (NTP correction / DST) — monotonic unaffected."""
        self.wall_ns += int(seconds * NS)


def make_clock(ft: FakeTime) -> CaptureClock:
    return CaptureClock(monotonic_ns=lambda: ft.mono_ns, wall_ns=lambda: ft.wall_ns)


def test_now_advances_with_monotonic_time() -> None:
    ft = FakeTime()
    clock = make_clock(ft)
    t0 = clock.now()
    ft.advance(2.5)
    assert clock.now() - t0 == timedelta(seconds=2.5)


def test_wall_clock_jump_does_not_affect_intervals() -> None:
    ft = FakeTime()
    clock = make_clock(ft)
    t0 = clock.now()
    ft.advance(1.0)
    ft.jump_wall(-3600)  # backwards NTP step: naive wall-clock delta would go negative
    t1 = clock.now()
    assert t1 - t0 == timedelta(seconds=1.0)
    assert t1 > t0


def test_resync_reports_and_corrects_drift() -> None:
    ft = FakeTime()
    clock = make_clock(ft)
    ft.advance(10.0)
    ft.jump_wall(-2.0)  # mapped clock is now 2s ahead of system time
    drift = clock.resync()
    assert abs(drift - 2.0) < 1e-9
    # After resync, mapped time matches system time again.
    assert abs(clock.now().timestamp() - ft.wall_ns / NS) < 1e-6


def test_microsecond_precision_preserved() -> None:
    ft = FakeTime()
    clock = make_clock(ft)
    ft.advance(0.000123)
    ft.mono_ns += 456_000  # extra 456 microseconds, mono only
    t = clock.now()
    expected_us = (ft.mono_ns - 5_000 * NS) // 1_000 % 1_000_000
    assert t.microsecond == expected_us
