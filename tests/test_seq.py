"""Sequence-gap detection (Doc 5 §6): monotonic +1 or an explicit gap event."""

from thorp.recorder.seq import SeqTracker


def test_first_observation_without_baseline_is_accepted() -> None:
    tracker = SeqTracker()
    assert tracker.observe(1, 7) is None
    assert tracker.last_seen(1) == 7


def test_sequential_messages_pass() -> None:
    tracker = SeqTracker()
    tracker.reset(1, 10)
    assert tracker.observe(1, 11) is None
    assert tracker.observe(1, 12) is None


def test_gap_detected_with_expected_and_size() -> None:
    tracker = SeqTracker()
    tracker.reset(1, 2)
    gap = tracker.observe(1, 5)
    assert gap is not None
    assert gap.expected == 3
    assert gap.received == 5
    assert gap.size == 2


def test_duplicate_flagged_as_negative_gap() -> None:
    tracker = SeqTracker()
    tracker.reset(1, 4)
    gap = tracker.observe(1, 4)
    assert gap is not None
    assert gap.size == -1


def test_keys_tracked_independently() -> None:
    tracker = SeqTracker()
    tracker.reset(1, 100)
    tracker.reset(2, 5)
    assert tracker.observe(1, 101) is None
    assert tracker.observe(2, 6) is None
    assert tracker.observe(1, 103) is not None


def test_reset_establishes_new_baseline_after_gap() -> None:
    tracker = SeqTracker()
    tracker.reset(1, 10)
    assert tracker.observe(1, 20) is not None
    tracker.reset(1, 1)  # fresh snapshot after resubscribe
    assert tracker.observe(1, 2) is None
