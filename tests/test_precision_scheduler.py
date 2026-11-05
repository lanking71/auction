from datetime import datetime, timedelta
from threading import Event

import pytest

from precision_scheduler import execution_time, monotonic_deadline, wait_until_ns


def test_execution_time_positive_and_negative_manual_offsets():
    target = datetime(2026, 11, 5, 23, 59, 59, 999900)
    assert execution_time(target, 100, 50) == target - timedelta(milliseconds=150)
    assert execution_time(target, 100, -50) == target - timedelta(milliseconds=50)


def test_manual_offset_range():
    with pytest.raises(ValueError):
        execution_time(datetime.now(), 0, 500.001)


def test_monotonic_deadline_handles_midnight_and_100us():
    now = datetime(2026, 11, 5, 23, 59, 59, 999950)
    target = datetime(2026, 11, 6, 0, 0, 0, 50)
    assert monotonic_deadline(target, now_wall=now, now_ns=1_000_000) == 1_100_000


def test_wait_is_cancelable():
    event = Event()
    event.set()
    assert wait_until_ns(10**18, event) is False


def test_wait_hits_deterministic_boundary():
    values = iter([0, 50_000, 99_999, 100_000])
    assert wait_until_ns(100_000, clock_ns=lambda: next(values)) is True
