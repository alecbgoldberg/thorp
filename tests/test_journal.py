"""JournalWriter: hourly rotation, append-on-restart, valid JSONL (Doc 5 §3)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from thorp.common.clock import CaptureClock
from thorp.common.records import RawMessageRecord
from thorp.recorder.journal import JournalSet, JournalWriter

from .test_clock import FakeTime, make_clock

NS = 1_000_000_000


def make_record(clock: CaptureClock, payload: str) -> RawMessageRecord:
    now = clock.now()
    return RawMessageRecord(venue="kalshi", receive_ts=now, process_ts=now, raw={"p": payload})


def wall_at(ft: FakeTime) -> datetime:
    return datetime.fromtimestamp(ft.wall_ns / NS, tz=UTC)


def test_writes_valid_json_lines_and_rotates_hourly(tmp_path: Path) -> None:
    # Anchor just before an hour boundary.
    ft = FakeTime(wall_start_ns=int(datetime(2026, 7, 20, 10, 59, 58, tzinfo=UTC).timestamp() * NS))
    clock = make_clock(ft)
    writer = JournalWriter(tmp_path, "kalshi", "ws_misc", clock, fsync_interval_s=0.0)

    writer.write(make_record(clock, "a"))
    ft.advance(1.0)
    writer.write(make_record(clock, "b"))
    ft.advance(5.0)  # crosses 11:00
    writer.write(make_record(clock, "c"))
    writer.close()

    day_dir = tmp_path / "kalshi" / "ws_misc" / "date=2026-07-20"
    file_10 = day_dir / "10.jsonl"
    file_11 = day_dir / "11.jsonl"
    assert file_10.exists() and file_11.exists()

    lines_10 = file_10.read_text().splitlines()
    lines_11 = file_11.read_text().splitlines()
    assert [json.loads(ln)["raw"]["p"] for ln in lines_10] == ["a", "b"]
    assert [json.loads(ln)["raw"]["p"] for ln in lines_11] == ["c"]
    assert writer.records_written == 3


def test_restart_within_hour_appends_not_truncates(tmp_path: Path) -> None:
    ft = FakeTime(wall_start_ns=int(datetime(2026, 7, 20, 14, 5, 0, tzinfo=UTC).timestamp() * NS))
    clock = make_clock(ft)

    first = JournalWriter(tmp_path, "kalshi", "trades", clock, fsync_interval_s=0.0)
    first.write(make_record(clock, "before-crash"))
    first.close()

    second = JournalWriter(tmp_path, "kalshi", "trades", clock, fsync_interval_s=0.0)
    second.write(make_record(clock, "after-restart"))
    second.close()

    path = tmp_path / "kalshi" / "trades" / "date=2026-07-20" / "14.jsonl"
    payloads = [json.loads(ln)["raw"]["p"] for ln in path.read_text().splitlines()]
    assert payloads == ["before-crash", "after-restart"]


def test_journal_set_routes_by_stream_and_reports_stats(tmp_path: Path) -> None:
    ft = FakeTime(wall_start_ns=int(datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC).timestamp() * NS))
    clock = make_clock(ft)
    journals = JournalSet(tmp_path, clock, fsync_interval_s=0.0)

    journals.write("kalshi", "trades", make_record(clock, "t1"))
    journals.write("kalshi", "book_deltas", make_record(clock, "d1"))
    journals.write("kalshi", "trades", make_record(clock, "t2"))
    journals.close()

    assert journals.stats() == {"kalshi/trades": 2, "kalshi/book_deltas": 1}
    assert (tmp_path / "kalshi" / "trades" / "date=2026-07-20" / "09.jsonl").exists()
    assert (tmp_path / "kalshi" / "book_deltas" / "date=2026-07-20" / "09.jsonl").exists()
