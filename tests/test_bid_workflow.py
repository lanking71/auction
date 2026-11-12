from datetime import datetime, timedelta
from threading import Event, Thread, Barrier
from types import SimpleNamespace
import time

import pytest
import Auction as module
from Auction import Auction, BatchGate
from bid_models import BidTaskSpec, BidTaskRuntime, BidResult
from bid_results import parse_record, reconcile
from precision_scheduler import ClockBridge


def test_browser_dom_uses_current_session_without_requests():
    auction = Auction()
    browser = SimpleNamespace(current_url="https://itempage3.auction.co.kr/test")
    browser.get = lambda url: None
    browser.execute_script = lambda script: {"title": "mock product", "price": "52,000원", "bid": True}
    spec = BidTaskSpec(browser.current_url, 53000, datetime.now(), "id")
    assert auction.load_product(spec, BidTaskRuntime(browser=browser), lambda: False) == 52000


def test_result_identity_and_history_must_be_unambiguous():
    clicked = datetime(2026, 1, 1, 12, 0, 0)
    exact = parse_record(["account", "2026-01-01 12:00:00.100000", "1,000원"])
    masked = parse_record(["acc***", "2026-01-01 12:00:00.100000", "1,000원"])
    kwargs = dict(account_id="account", price=1000, clicked=clicked,
                  returned=clicked + timedelta(seconds=1), server_uncertainty_ms=0.1)
    assert reconcile([], [masked], **kwargs)["accepted"] is None
    assert reconcile([exact], [exact], **kwargs)["accepted"] is None
    assert reconcile([], [exact, exact], **kwargs)["accepted"] is None
    assert reconcile([], [exact], **kwargs)["accepted"] is True
    kwargs["server_uncertainty_ms"] = None
    assert reconcile([], [exact], **kwargs)["accepted"] is None


def test_rank_is_separate_from_acceptance():
    clicked = datetime(2026, 1, 1, 12)
    other = parse_record(["other", "2026-01-01 12:00:00.200000", "2,000원"])
    mine = parse_record(["account", "2026-01-01 12:00:00.100000", "1,000원"])
    v = reconcile([], [other, mine], account_id="account", price=1000, clicked=clicked,
                  returned=clicked + timedelta(seconds=1), server_uncertainty_ms=0.1)
    assert v["accepted"] is True and v["rank"] == 2


def test_batch_failed_participant_unblocks_other_task():
    gate = BatchGate(2, time.perf_counter_ns() + 1_000_000_000)
    answers = []
    thread = Thread(target=lambda: answers.append(gate.arrive("ready", "one", lambda: False)))
    thread.start()
    gate.abort("second_failed")
    thread.join(1)
    assert answers == [False]


def test_cleanup_attempts_session_even_if_browser_quit_fails():
    closed = []
    def broken():
        raise RuntimeError("quit failed")
    runtime = BidTaskRuntime(browser=SimpleNamespace(quit=broken),
                             session=SimpleNamespace(close=lambda: closed.append(True)))
    runtime.close()
    assert closed == [True] and runtime.cleanup_errors
    runtime.close()
    assert closed == [True]


@pytest.mark.parametrize("receipt", [{"state": "cancelled"}, {"state": "fired", "page": "mock", "clicked": 50.0}])
def test_lost_arm_ack_never_reclicks_and_propagates_result(monkeypatch, receipt):
    auction = Auction()
    field = SimpleNamespace(clear=lambda: None, send_keys=lambda value: None)
    browser = SimpleNamespace(find_element=lambda *args: field, quit=lambda: None)
    monkeypatch.setattr(auction, "setupbrowser", lambda: (browser, False))
    monkeypatch.setattr(auction, "loginstart", lambda *args: True)
    monkeypatch.setattr(auction, "load_product", lambda *args: 100)
    monkeypatch.setattr(auction, "read_records", lambda *args: [])
    monkeypatch.setattr(auction, "bidWindow", lambda *args: ("main", "popup"))
    monkeypatch.setattr(auction, "_collect", lambda *args: None)
    reports = []
    monkeypatch.setattr(auction, "_report", reports.append)
    bridge = ClockBridge("mock", time.perf_counter_ns(), 0, 0.1, datetime.now())
    monkeypatch.setattr(module, "sample_browser_clock", lambda browser: bridge)
    attempts = []
    def arm(*args, **kwargs):
        attempts.append(1)
        raise TimeoutError("ack lost after browser scheduled")
    monkeypatch.setattr(module, "arm_browser_timer", arm)
    monkeypatch.setattr(module, "timer_command", lambda *args: receipt)
    spec = BidTaskSpec("https://itempage3.auction.co.kr/test", 123, datetime.now()+timedelta(seconds=10), "id")
    result, runtime = BidResult(spec), BidTaskRuntime()
    result.timing["execution_target"] = spec.target_server_time
    auction.process_task(spec, runtime, result, time.perf_counter_ns()+10_000_000_000,
                         BatchGate(1, time.perf_counter_ns()+5_000_000_000), lambda: False)
    assert attempts == [1] and reports == [result]
    assert result.error.startswith("TimeoutError")
    assert result.status == receipt["state"]


def test_batch_keeps_specs_results_and_exceptions_connected(monkeypatch):
    auction = Auction()
    sync = Barrier(2)
    monkeypatch.setattr(auction, "setupbrowser", lambda: (SimpleNamespace(quit=lambda: None), False))
    monkeypatch.setattr(auction, "loginstart", lambda *args: True)
    def load(spec, *args):
        sync.wait(timeout=1)
        raise RuntimeError(f"task-price-{spec.price}")
    monkeypatch.setattr(auction, "load_product", load)
    monkeypatch.setattr(auction, "_report", lambda result: None)
    specs = [BidTaskSpec("https://itempage3.auction.co.kr/test", price,
                        datetime.now()+timedelta(seconds=10+i), str(i)) for i, price in enumerate([100, 200])]
    auction.auctionStart(specs, [])
    for spec, result in zip(specs, auction.last_results):
        assert result.task == spec
        assert result.status == "failed" and str(spec.price) in result.error


def test_past_target_does_not_start_browser(monkeypatch):
    auction = Auction()
    def forbidden():
        pytest.fail("expired target opened browser")
    monkeypatch.setattr(auction, "setupbrowser", forbidden)
    monkeypatch.setattr(auction, "_report", lambda result: None)
    auction.auctionStart([BidTaskSpec("https://www.auction.co.kr/test", 1, datetime.now()-timedelta(seconds=1), "id")], [])
    assert auction.last_results[0].status == "expired"


def test_wall_clock_jump_invalidates_learning_without_moving_deadline(monkeypatch):
    spec = BidTaskSpec("https://www.auction.co.kr/mock", 1, datetime.now(), "id")
    result = BidResult(spec)
    anchor = datetime(2026, 11, 12, 12)
    result.timing.update(wall_anchor=anchor, monotonic_anchor_ns=100, deadline_ns=2000000100)
    monkeypatch.setattr(module.time, "perf_counter_ns", lambda: 1000000100)
    monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda: anchor+timedelta(seconds=31)))
    assert Auction._wall_clock_changed(result)
    assert result.timing["deadline_ns"] == 2000000100
    assert result.timing["wall_clock_change_ms"] == 30000


def test_expired_bid_reports_which_program_and_why_it_was_not_submitted():
    auction = Auction()
    spec = BidTaskSpec("https://www.auction.co.kr/mock", 1000, datetime.now(), "id")
    result = BidResult(spec, status="expired")
    result.timing.update(preparation_stage="wait_receipt",
                         browser_receipt={"state": "expired", "error": "not_enabled_before_deadline"})
    messages, events = [], []
    auction.auction_operation_signal.connect(messages.append)
    auction.bid_logger = SimpleNamespace(write=events.append)
    auction._report(result)
    assert any("장전 활성화" in message for message in messages)
    assert events[0]["process_id"] > 0
    assert events[0]["task_id"] == spec.task_id
