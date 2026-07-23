"""Heartbeat + Watchdog dead-man switch (Doc 4 §8)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from thorp.engine.heartbeat import HeartbeatReader, HeartbeatWriter
from thorp.engine.watchdog import SimKillAction, Watchdog


def test_heartbeat_write_read_age(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    w = HeartbeatWriter(path)
    t0 = datetime(2026, 7, 22, 20, 0, 0, tzinfo=UTC)
    w.beat(t0)
    r = HeartbeatReader(path)
    assert r.last_beat() == t0
    assert r.age_s(t0 + timedelta(seconds=7)) == 7.0


def test_missing_heartbeat_is_infinite_age(tmp_path: Path) -> None:
    assert HeartbeatReader(tmp_path / "none").age_s() == float("inf")


async def test_sim_kill_writes_halt_flag_no_venue_call(tmp_path: Path) -> None:
    flag = tmp_path / "halt.flag"
    remaining = await SimKillAction(flag)()
    assert remaining == 0  # nothing live to cancel in sim
    assert flag.exists() and "dead-man" in flag.read_text()


async def test_watchdog_fires_when_heartbeat_stale(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    HeartbeatWriter(path).beat(datetime(2026, 7, 22, 20, 0, 0, tzinfo=UTC))
    flag = tmp_path / "halt.flag"
    # clock is 30s after the beat -> stale (> 10s)
    now = datetime(2026, 7, 22, 20, 0, 30, tzinfo=UTC)
    wd = Watchdog(HeartbeatReader(path), SimKillAction(flag),
                  stale_threshold_s=10, clock=lambda: now)
    assert await wd.check_once() is True
    assert flag.exists()
    # already fired -> does not fire again
    assert await wd.check_once() is False


async def test_watchdog_does_not_fire_when_healthy(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    now = datetime(2026, 7, 22, 20, 0, 0, tzinfo=UTC)
    HeartbeatWriter(path).beat(now)
    flag = tmp_path / "halt.flag"
    wd = Watchdog(HeartbeatReader(path), SimKillAction(flag),
                  stale_threshold_s=10, clock=lambda: now + timedelta(seconds=3))
    assert await wd.check_once() is False
    assert not flag.exists()


async def test_watchdog_rearms_after_recovery(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    flag = tmp_path / "halt.flag"
    times = {"now": datetime(2026, 7, 22, 20, 0, 30, tzinfo=UTC)}
    HeartbeatWriter(path).beat(datetime(2026, 7, 22, 20, 0, 0, tzinfo=UTC))
    wd = Watchdog(HeartbeatReader(path), SimKillAction(flag),
                  stale_threshold_s=10, clock=lambda: times["now"])
    assert await wd.check_once() is True  # stale -> fires
    # heartbeat recovers (fresh beat at the current clock)
    HeartbeatWriter(path).beat(times["now"])
    assert await wd.check_once() is False  # healthy -> re-arms
    # goes stale again later -> fires again
    HeartbeatWriter(path).beat(times["now"])
    times["now"] = times["now"] + timedelta(seconds=30)
    assert await wd.check_once() is True


async def test_watchdog_escalates_when_flatten_unconfirmed(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    HeartbeatWriter(path).beat(datetime(2026, 7, 22, 20, 0, 0, tzinfo=UTC))
    now = datetime(2026, 7, 22, 20, 0, 30, tzinfo=UTC)
    calls = {"n": 0}

    class StubbornKill:
        async def __call__(self) -> int:
            calls["n"] += 1
            return 3  # orders never confirm flat -> watchdog must escalate

    wd = Watchdog(HeartbeatReader(path), StubbornKill(),
                  stale_threshold_s=10, max_retries=3, retry_backoff_s=0, clock=lambda: now)
    await wd.check_once()
    assert calls["n"] == 3  # retried max_retries times, then escalated
