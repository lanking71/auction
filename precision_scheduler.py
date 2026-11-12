from __future__ import annotations

import contextlib
import ctypes
import os
import time
import math
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta
from threading import Event
from typing import Callable


TIMER_SCRIPT = Path(__file__).with_name("browser_timer.js").read_text(encoding="utf-8")


@dataclass(frozen=True)
class ClockBridge:
    page: str
    python_ns: int
    browser_ms: float
    uncertainty_ms: float
    wall_time: datetime

    def browser_target(self, deadline_ns: int) -> float:
        return self.browser_ms + (deadline_ns - self.python_ns) / 1_000_000

    def python_time(self, browser_ms: float) -> int:
        return self.python_ns + round((browser_ms - self.browser_ms) * 1_000_000)

    def wall_at(self, browser_ms: float) -> datetime:
        return self.wall_time + timedelta(milliseconds=browser_ms - self.browser_ms)


def sample_browser_clock(browser, samples: int = 7) -> ClockBridge:
    candidates = []
    for _ in range(samples):
        before = time.perf_counter_ns()
        wall = datetime.now()
        value = browser.execute_script(TIMER_SCRIPT, "clock", {})
        after = time.perf_counter_ns()
        if not value or not math.isfinite(float(value["now"])):
            raise RuntimeError("browser clock unavailable")
        midpoint = (before + after) // 2
        candidates.append(ClockBridge(str(value["page"]), midpoint, float(value["now"]),
                                      (after - before) / 2_000_000 + 0.1,
                                      wall + timedelta(microseconds=(midpoint - before) / 1000)))
    if not candidates or len({c.page for c in candidates}) != 1:
        raise RuntimeError("page changed during clock sampling")
    return min(candidates, key=lambda c: c.uncertainty_ms)


def execution_time(target_server_time: datetime, automatic_ms: float, manual_ms: float) -> datetime:
    if not -500.0 <= manual_ms <= 500.0:
        raise ValueError("manual offset must be between -500 and 500 ms")
    return target_server_time - timedelta(milliseconds=automatic_ms + manual_ms)


def monotonic_deadline(target_wall_time: datetime, now_wall: datetime | None = None,
                       now_ns: int | None = None) -> int:
    wall = now_wall or datetime.now(target_wall_time.tzinfo)
    mono = time.perf_counter_ns() if now_ns is None else now_ns
    return mono + int((target_wall_time - wall).total_seconds() * 1_000_000_000)


@contextlib.contextmanager
def windows_precision_window():
    timer_set = False
    old_priority = None
    priority_set = False
    kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
    winmm = getattr(getattr(ctypes, "windll", None), "winmm", None)
    try:
        if os.name == "nt" and winmm:
            winmm.timeBeginPeriod.argtypes = [ctypes.c_uint]
            winmm.timeBeginPeriod.restype = ctypes.c_uint
            winmm.timeEndPeriod.argtypes = [ctypes.c_uint]
            winmm.timeEndPeriod.restype = ctypes.c_uint
            timer_set = winmm.timeBeginPeriod(1) == 0
        if os.name == "nt" and kernel32:
            kernel32.GetCurrentThread.argtypes = []
            kernel32.GetCurrentThread.restype = ctypes.c_void_p
            kernel32.GetThreadPriority.argtypes = [ctypes.c_void_p]
            kernel32.GetThreadPriority.restype = ctypes.c_int
            kernel32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            kernel32.SetThreadPriority.restype = ctypes.c_int
            thread = kernel32.GetCurrentThread()
            old_priority = kernel32.GetThreadPriority(thread)
            if old_priority != 0x7FFFFFFF:
                priority_set = bool(kernel32.SetThreadPriority(thread, 2))
        yield
    finally:
        try:
            if priority_set and not kernel32.SetThreadPriority(thread, old_priority):
                raise OSError("thread priority restoration failed")
        finally:
            if timer_set and winmm.timeEndPeriod(1) != 0:
                raise OSError("timer resolution restoration failed")


def wait_until_ns(deadline_ns: int, cancel_event: Event | None = None,
                  clock_ns: Callable[[], int] = time.perf_counter_ns) -> bool:
    cancel_event = cancel_event or Event()
    with windows_precision_window():
        while True:
            if cancel_event.is_set():
                return False
            remaining = deadline_ns - clock_ns()
            if remaining <= 0:
                return True
            if remaining > 20_000_000:
                cancel_event.wait(min((remaining - 20_000_000) / 1e9, 0.25))
            elif remaining > 2_000_000:
                time.sleep(max((remaining - 2_000_000) / 1e9, 0))
            else:
                # Last 2 ms intentionally busy-spin. 100 us is a scheduler target,
                # not an end-to-end guarantee through Chrome and the network.
                pass


def arm_browser_timer(browser, deadline_ns: int, cancel_event: Event | None = None,
                      *, task_id: str, bridge: ClockBridge, late_limit_ms: float = 5.0) -> dict:
    if cancel_event and cancel_event.is_set():
        return {"state": "cancelled"}
    if deadline_ns <= time.perf_counter_ns():
        return {"state": "expired"}
    return browser.execute_script(TIMER_SCRIPT, "arm", {
        "id": task_id, "page": bridge.page, "target": bridge.browser_target(deadline_ns),
        "late_limit": late_limit_ms,
    })


def timer_command(browser, task_id: str, action: str = "status") -> dict:
    return browser.execute_script(TIMER_SCRIPT, action, {"id": task_id})
