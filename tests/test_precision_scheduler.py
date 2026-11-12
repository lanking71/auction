from datetime import datetime, timedelta
from threading import Event

import pytest

from precision_scheduler import execution_time, monotonic_deadline, wait_until_ns
from precision_scheduler import ClockBridge, sample_browser_clock, windows_precision_window
import precision_scheduler as scheduler
from types import SimpleNamespace


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


def test_clock_bridge_uses_absolute_target_and_excludes_arm_wait():
    wall = datetime(2026, 11, 5, 23, 59, 59, 900000)
    bridge = ClockBridge("page", 1_000_000_000, 500, .2, wall)
    assert bridge.browser_target(1_200_000_000) == 700
    assert bridge.python_time(700) == 1_200_000_000
    clicked = bridge.wall_at(700)
    assert clicked == datetime(2026, 11, 6, 0, 0, 0, 100000)
    # A server timestamp 20ms after the click is independent of arm lead time.
    registered = clicked + timedelta(milliseconds=20)
    for lead_ms in (10, 100, 5000):
        armed = clicked - timedelta(milliseconds=lead_ms)
        assert registered > armed
        assert (registered - bridge.wall_at(700)).total_seconds() == .02


def test_clock_sampling_rejects_page_changes():
    pages = iter(["a", "b"])
    browser = SimpleNamespace(execute_script=lambda *args: {"page": next(pages), "now": 1})
    with pytest.raises(RuntimeError, match="page changed"):
        sample_browser_clock(browser, samples=2)


def test_windows_settings_restored_after_exception_and_nested_use(monkeypatch):
    import ctypes
    calls = []
    class Fn:
        def __init__(self, name, result):
            self.name, self.result = name, result
        def __call__(self, *args):
            calls.append((self.name, args))
            return self.result
    kernel = SimpleNamespace(GetCurrentThread=Fn("thread", 123),
        GetThreadPriority=Fn("get_priority", 0), SetThreadPriority=Fn("set_priority", 1))
    mm = SimpleNamespace(timeBeginPeriod=Fn("begin", 0), timeEndPeriod=Fn("end", 0))
    monkeypatch.setattr(scheduler, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(scheduler, "ctypes", SimpleNamespace(windll=SimpleNamespace(kernel32=kernel, winmm=mm),
        c_uint=ctypes.c_uint, c_int=ctypes.c_int, c_void_p=ctypes.c_void_p))
    with pytest.raises(ValueError):
        with windows_precision_window():
            with windows_precision_window():
                raise ValueError("injected failure")
    assert len([c for c in calls if c[0] == "begin"]) == 2
    assert len([c for c in calls if c[0] == "end"]) == 2
    assert [c[1][1] for c in calls if c[0] == "set_priority"] == [2, 2, 0, 0]
