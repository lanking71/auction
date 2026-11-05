from __future__ import annotations

import contextlib
import ctypes
import os
import time
from datetime import datetime, timedelta
from threading import Event
from typing import Callable


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
    kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
    winmm = getattr(getattr(ctypes, "windll", None), "winmm", None)
    try:
        if os.name == "nt" and winmm:
            timer_set = winmm.timeBeginPeriod(1) == 0
        if os.name == "nt" and kernel32:
            thread = kernel32.GetCurrentThread()
            old_priority = kernel32.GetThreadPriority(thread)
            kernel32.SetThreadPriority(thread, 2)  # THREAD_PRIORITY_HIGHEST
        yield
    finally:
        if os.name == "nt" and kernel32 and old_priority is not None:
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), old_priority)
        if timer_set and winmm:
            winmm.timeEndPeriod(1)


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


def arm_browser_timer(browser, deadline_ns: int, cancel_event: Event | None = None) -> dict:
    if cancel_event and cancel_event.is_set():
        return {"cancelled": True}
    delay_ms = max(0.0, (deadline_ns - time.perf_counter_ns()) / 1_000_000)
    script = r"""
const done = arguments[arguments.length - 1];
const delay = Math.max(0, Number(arguments[0]));
const start = performance.now();
const target = start + delay;
const button = document.querySelector('input#buttonBid');
if (!button) { done({ok:false, error:'buttonBid not found'}); return; }
function finish() {
  while (performance.now() < target) {}
  const clicked = performance.now();
  button.click();
  done({ok:true, start:start, target:target, clicked:clicked});
}
setTimeout(finish, Math.max(0, delay - 20));
"""
    browser.set_script_timeout(max(30.0, delay_ms / 1000 + 5.0))
    return browser.execute_async_script(script, delay_ms)
