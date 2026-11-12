"""Opt-in real Chrome tests, all traffic restricted to the loopback fixture."""
import os
import time
from datetime import datetime, timedelta
from threading import Event

import pytest

from Auction import Auction
from bid_models import BidTaskSpec, BidTaskRuntime, BidResult
from precision_scheduler import arm_browser_timer, sample_browser_clock, timer_command
from scripts.mock_auction import local_browser, mock_server
import auction_login

pytestmark = pytest.mark.skipif(os.environ.get("AUCTON_LOCAL_BROWSER_TESTS") != "1",
                                reason="opt-in local Chrome integration tests")


@pytest.fixture(scope="module")
def local():
    with mock_server() as (url, rows):
        browser = local_browser()
        try:
            yield browser, url, rows
        finally:
            browser.quit()


def arm(browser, url, task, lead_ms=200, late_limit_ms=100):
    browser.get(url)
    browser.execute_script("window.mockTask=arguments[0]", task)
    bridge = sample_browser_clock(browser)
    deadline = time.perf_counter_ns() + int(lead_ms * 1e6)
    ack = arm_browser_timer(browser, deadline, task_id=task, bridge=bridge,
                            late_limit_ms=late_limit_ms)
    return bridge, deadline, ack


def wait_done(browser, task):
    end = time.perf_counter()+3
    while time.perf_counter() < end:
        value = timer_command(browser, task)
        if value["state"] != "armed":
            return value
        time.sleep(0.01)
    pytest.fail("timer did not finish")


def test_arm_ack_is_separate_and_duplicate_id_cannot_click_twice(local):
    browser, url, rows = local
    bridge, deadline, ack = arm(browser, url, "once")
    assert ack["state"] == "armed" and time.perf_counter_ns() < deadline
    timer_command(browser, "once", "enable")
    receipt = wait_done(browser, "once")
    assert receipt["state"] == "fired" and receipt["clicked"] >= receipt["target"]
    arm_browser_timer(browser, deadline+1_000_000_000, task_id="once", bridge=bridge)
    assert browser.execute_script("return mockClicks.length") == 1


def test_cancel_acknowledgement_prevents_click(local):
    browser, url, rows = local
    arm(browser, url, "cancel")
    timer_command(browser, "cancel", "enable")
    assert timer_command(browser, "cancel", "cancel")["state"] == "cancelled"
    time.sleep(0.25)
    assert browser.execute_script("return mockClicks.length") == 0


def test_uncommitted_timer_and_past_target_never_click(local):
    browser, url, rows = local
    arm(browser, url, "no-enable", lead_ms=80)
    receipt = wait_done(browser, "no-enable")
    assert receipt["state"] == "expired"
    assert receipt["error"] == "not_enabled_before_deadline"
    bridge = sample_browser_clock(browser)
    ack = arm_browser_timer(browser, time.perf_counter_ns()-1, task_id="past", bridge=bridge)
    assert ack["state"] == "expired"
    assert browser.execute_script("return mockClicks.length") == 0


def test_page_navigation_does_not_rearm_or_reclick(local):
    browser, url, rows = local
    bridge, deadline, _ = arm(browser, url, "navigation", lead_ms=500)
    timer_command(browser, "navigation", "enable")
    browser.get(url + "/next")
    current = sample_browser_clock(browser)
    assert current.page != bridge.page
    assert timer_command(browser, "navigation")["state"] == "unknown"
    assert timer_command(browser, "navigation", "cancel")["state"] == "unknown"
    assert timer_command(browser, "navigation", "enable")["state"] == "unknown"
    time.sleep(0.55)
    assert browser.execute_script("return mockClicks.length") == 0


def test_normal_mode_uses_fresh_price_and_checks_limit(local):
    browser, url, rows = local
    auction = Auction()
    messages = []
    auction.auction_operation_signal.connect(messages.append)
    runtime = BidTaskRuntime(browser=browser)
    browser.get(url)
    # Change only the old DOM. refresh must discard it and use the server's 1000.
    browser.execute_script("document.querySelector('tbody .price').textContent='9,000원'")
    spec = BidTaskSpec("https://www.auction.co.kr/mock", 0, datetime.now(), "mock",
                      fixed_price=False, max_price=1100, additional_amount=100)
    result = BidResult(spec)
    auction.refresh(browser, spec, runtime, result, lambda: False)
    assert result.submitted_price == 1100
    assert browser.execute_script("return mockClicks[0].price") == 1100
    # On a second page refresh current DOM price is 1000; tighter limit rejects.
    spec = BidTaskSpec(spec.url, 0, datetime.now(), "mock", fixed_price=False,
                      max_price=1050, additional_amount=100)
    result = BidResult(spec)
    auction.refresh(browser, spec, runtime, result, lambda: False)
    assert result.status == "over_limit"
    assert browser.execute_script("return mockClicks.length") == 0
    assert any('1,100원' in line and '1,050원' in line for line in messages)
    assert any('한도를 초과' in line for line in messages)


def test_response_loss_cannot_make_a_second_submission(local):
    browser, url, rows = local
    bridge, deadline, _ = arm(browser, url, "response-loss")
    timer_command(browser, "response-loss", "enable")
    receipt = wait_done(browser, "response-loss")
    assert receipt["state"] == "fired"
    # The caller loses this response. The durable receipt still prevents rearming.
    recovered = timer_command(browser, "response-loss", "cancel")
    assert recovered["state"] == "fired"
    arm_browser_timer(browser, deadline+1_000_000_000, task_id="response-loss", bridge=bridge)
    assert browser.execute_script("return mockClicks.length") == 1


def test_lost_arm_ack_is_cancelled_without_click(local):
    browser, url, rows = local
    browser.get(url)
    bridge = sample_browser_clock(browser)
    class Lossy:
        def execute_script(self, script, action, options):
            browser.execute_script(script, action, options)
            raise TimeoutError("arm ack lost")
    with pytest.raises(TimeoutError):
        arm_browser_timer(Lossy(), time.perf_counter_ns()+200_000_000,
                          task_id="arm-loss", bridge=bridge)
    assert timer_command(browser, "arm-loss", "cancel")["state"] == "cancelled"
    time.sleep(.25)
    assert browser.execute_script("return mockClicks.length") == 0


def test_current_browser_product_dom_and_full_local_workflow(local, monkeypatch):
    browser, url, rows = local
    auction = Auction()
    monkeypatch.setattr(auction, "validate_url", lambda value: None)
    spec = BidTaskSpec(url, 4321, datetime.now()+timedelta(seconds=8), "mock")
    assert auction.load_product(spec, BidTaskRuntime(browser=browser), lambda: False) == 1000
    # Full task owns and closes a second browser, without any live login/bid.
    monkeypatch.setattr(auction, "setupbrowser", lambda: (local_browser(), False))
    monkeypatch.setattr(auction, "loginstart", lambda *args: True)
    monkeypatch.setattr(auction, "_report", lambda result: None)
    start = len(rows)
    auction.auctionStart([spec], [])
    assert auction.last_results[0].browser_clicked_at is not None
    assert auction.last_results[0].status == "unknown"
    assert len(rows) == start + 1 and rows[-1]["price"] == 4321


def test_two_complete_tasks_keep_prices_and_deadlines_separate(local, monkeypatch):
    browser, url, rows = local
    auction = Auction()
    monkeypatch.setattr(auction, "validate_url", lambda value: None)
    monkeypatch.setattr(auction, "setupbrowser", lambda: (local_browser(), False))
    monkeypatch.setattr(auction, "loginstart", lambda *args: True)
    monkeypatch.setattr(auction, "_report", lambda result: None)
    now = datetime.now()
    specs = [BidTaskSpec(url, 5100, now+timedelta(seconds=10), "first"),
             BidTaskSpec(url, 6200, now+timedelta(seconds=10.1), "second")]
    start = len(rows)
    auction.auctionStart(specs, [])
    assert [r.task.task_id for r in auction.last_results] == [s.task_id for s in specs]
    assert [r.submitted_price for r in auction.last_results] == [5100, 6200]
    assert all(r.browser_clicked_at is not None for r in auction.last_results)
    assert sorted(r["price"] for r in rows[start:]) == [5100, 6200]


def local_login(monkeypatch, url):
    monkeypatch.setattr(auction_login, 'LOGIN_URL', url + '/login')
    def validate(value):
        assert value.startswith(url + '/')
    monkeypatch.setattr(auction_login, 'validate_login_origin', validate)


def test_headless_local_auto_login_submits_selected_account(local, monkeypatch):
    browser, url, rows = local
    local_login(monkeypatch, url)
    before = len(rows.login_ids)
    auction = Auction()
    assert auction_login.automatic_login(browser, 'selected-account', 'local-test-password',
        lambda: False, time.perf_counter_ns()+10_000_000_000, auction.verify_login)
    assert rows.login_ids[before:] == ['selected-account']
    assert auction.verify_login(browser)


def test_bad_auto_login_submits_once_and_never_bids(local, monkeypatch):
    browser, url, rows = local
    local_login(monkeypatch, url)
    before_login, before_bid = len(rows.login_ids), len(rows)
    with pytest.raises(auction_login.LoginError) as error:
        auction_login.automatic_login(browser, 'selected-account', 'wrong-local-password',
            lambda: False, time.perf_counter_ns()+10_000_000_000, Auction().verify_login)
    assert 'wrong-local-password' not in str(error.value)
    assert len(rows.login_ids) == before_login + 1 and len(rows) == before_bid


def test_password_blur_moves_button_but_auto_login_still_submits_once(local, monkeypatch):
    browser, url, rows = local
    local_login(monkeypatch, url)
    monkeypatch.setattr(auction_login, 'LOGIN_URL', url + '/login-shift')
    before_login, before_bid = len(rows.login_ids), len(rows)
    # The former sequence silently loses its click on this layout change.
    browser.get(url + '/login-shift')
    browser.find_element('css selector', '#typeMemberInputId').send_keys('selected-account')
    browser.find_element('css selector', '#typeMemberInputPassword').send_keys('local-test-password')
    browser.find_element('css selector', '#btnLogin').click()
    assert len(rows.login_ids) == before_login
    assert browser.current_url == url + '/login-shift'
    assert auction_login.automatic_login(browser, 'selected-account', 'local-test-password',
        lambda: False, time.perf_counter_ns()+10_000_000_000, Auction().verify_login)
    assert rows.login_ids[before_login:] == ['selected-account']
    assert len(rows) == before_bid


def test_auto_login_challenge_stops_without_submission(local, monkeypatch):
    browser, url, rows = local
    local_login(monkeypatch, url)
    monkeypatch.setattr(auction_login, 'LOGIN_URL', url + '/challenge')
    before_login, before_bid = len(rows.login_ids), len(rows)
    with pytest.raises(auction_login.LoginError, match='보안문자'):
        auction_login.automatic_login(browser, 'selected-account', 'local-test-password',
            lambda: False, time.perf_counter_ns()+10_000_000_000, Auction().verify_login)
    assert len(rows.login_ids) == before_login and len(rows) == before_bid
