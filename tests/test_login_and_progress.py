from datetime import datetime, timedelta
from types import SimpleNamespace
import time
import pytest

import Auction as module
import auction_login
from Auction import Auction, BatchGate
from bid_models import BidTaskSpec, BidTaskRuntime, BidResult


def test_login_origin_refuses_credentials_on_another_site():
    with pytest.raises(auction_login.LoginError):
        auction_login.validate_login_origin('https://example.com/login')
    with pytest.raises(auction_login.LoginError):
        auction_login.validate_login_origin('http://signin.auction.co.kr/')
    auction_login.validate_login_origin('https://signin.auction.co.kr/Authenticate/Default.aspx')
    with pytest.raises(auction_login.LoginError):
        auction_login.validate_login_origin('https://signin.auction.co.kr:444/login')
    with pytest.raises(auction_login.LoginError):
        auction_login.validate_login_origin('https://user:secret@signin.auction.co.kr/login')


def test_login_route_uses_the_verified_login_entry_not_default():
    assert '/Authenticate/Login.aspx?' in auction_login.LOGIN_URL
    assert '/Default.aspx' not in auction_login.LOGIN_URL


def test_redirect_to_error_page_never_reaches_credential_fields():
    browser = SimpleNamespace(get=lambda url: None,
        current_url='https://www.auction.co.kr/error/default.asp?private=hidden',
        execute_script=lambda *args: False, find_elements=lambda *args: [])
    with pytest.raises(auction_login.LoginError) as error:
        auction_login.automatic_login(browser, 'selected-account', 'never-enter-this-secret',
            lambda: False, time.perf_counter_ns()+1_000_000_000, lambda b: False)
    assert 'error/default.asp' in str(error.value)
    assert 'hidden' not in str(error.value) and 'never-enter-this-secret' not in str(error.value)


def test_hidden_bot_check_is_reported_before_any_credential_entry(monkeypatch):
    ticks = [0]
    def clock():
        ticks[0] += 2_000_000_000
        return ticks[0]
    monkeypatch.setattr(auction_login, 'time', SimpleNamespace(perf_counter_ns=clock, sleep=lambda delay: None))
    browser = SimpleNamespace(get=lambda url: None,
        current_url='https://signin.auction.co.kr/Authenticate/Login.aspx',
        execute_script=lambda *args: True, find_elements=lambda *args: [])
    with pytest.raises(auction_login.LoginChallengeError, match='봇 확인'):
        auction_login.automatic_login(browser, 'selected-account', 'never-enter-this-secret',
            lambda: False, 90_000_000_000, lambda b: False)


def test_existing_validation_text_is_not_a_failed_login_before_submit():
    error_element = SimpleNamespace(is_displayed=lambda: True, text='Login error')
    browser = SimpleNamespace(find_elements=lambda by, selector:
        [] if 'iframe' in selector else [error_element])
    auction_login._check_challenge(browser)
    with pytest.raises(auction_login.LoginError):
        auction_login._check_challenge(browser, after_submit=True)


def test_login_transport_failure_does_not_expose_password():
    password = 'secret-must-not-appear'
    def broken_get(url):
        raise RuntimeError('request password=' + password)
    browser = SimpleNamespace(get=broken_get)
    with pytest.raises(auction_login.LoginError) as error:
        auction_login.automatic_login(browser, 'id', password, lambda: False,
                                     time.perf_counter_ns()+1_000_000_000, lambda b: False)
    assert password not in str(error.value)


@pytest.mark.parametrize('clears', [False, True])
def test_post_login_bot_check_waits_but_never_repeats_submit(monkeypatch, clears):
    ticks, clicks, messages, checks = [0], [], [], [0]
    def now():
        ticks[0] += 1_000_000_000
        return ticks[0]
    field = SimpleNamespace(clear=lambda: None, send_keys=lambda value: None)
    button = SimpleNamespace(click=lambda: clicks.append(True))
    monkeypatch.setattr(auction_login, 'time', SimpleNamespace(perf_counter_ns=now, sleep=lambda delay: None))
    monkeypatch.setattr(auction_login, 'prepare_login_form', lambda *args: (field, field, button))
    monkeypatch.setattr(auction_login, '_settle_login_button', lambda *args: button)
    monkeypatch.setattr(auction_login, '_check_challenge', lambda *args, **kwargs: None)
    monkeypatch.setattr(auction_login, '_is_bot_check', lambda browser: True)
    def verify(browser):
        checks[0] += 1
        return clears and checks[0] == 3
    browser = SimpleNamespace(current_url=auction_login.LOGIN_URL)
    args = (browser, 'selected-account', 'local-secret', lambda: False, 90_000_000_000, verify, messages.append)
    if clears:
        assert auction_login.automatic_login(*args)
    else:
        with pytest.raises(auction_login.LoginChallengeError, match='봇 확인'):
            auction_login.automatic_login(*args)
    assert clicks == [True]
    assert sum('브라우저 확인' in m for m in messages) == 1


@pytest.mark.parametrize('automatic', [False, True])
def test_mode_routes_browser_visibility_per_task(monkeypatch, automatic):
    auction = Auction()
    calls = []
    browser = SimpleNamespace(quit=lambda: None)
    def setup(**kwargs):
        calls.append(kwargs)
        return browser, False
    monkeypatch.setattr(auction, 'setupbrowser', setup)
    monkeypatch.setattr(auction, 'loginstart', lambda *args: False)
    monkeypatch.setattr(auction, '_report', lambda result: None)
    spec = BidTaskSpec('https://www.auction.co.kr/mock', 1000, datetime.now()+timedelta(minutes=1),
                       'id', automatic_login=automatic)
    auction.process_task(spec, BidTaskRuntime(), BidResult(spec), time.perf_counter_ns()+60_000_000_000,
                         BatchGate(1, time.perf_counter_ns()+50_000_000_000), lambda: False)
    assert calls == ([{}] if automatic else [{}])


def test_auto_login_uses_spec_account_and_never_requests_manual_button(monkeypatch):
    auction = Auction()
    spec = BidTaskSpec('https://www.auction.co.kr/mock', 1000, datetime.now(),
                       'selected-account', automatic_login=True)
    password_reads, submitted, manual_requests = [], [], []
    monkeypatch.setattr(module, 'get_password', lambda account: password_reads.append(account) or 'local-secret')
    monkeypatch.setattr(module, 'automatic_login', lambda browser, account, password, *args:
                        submitted.append((account, password)) or True)
    auction.login_needed_signal.connect(lambda: manual_requests.append(True))
    runtime = BidTaskRuntime(browser=SimpleNamespace(get=lambda url: None))
    assert auction.loginstart(spec, runtime, lambda: False, time.perf_counter_ns()+10_000_000_000)
    assert password_reads == ['selected-account']
    assert submitted == [('selected-account', 'local-secret')] and not manual_requests
    assert 'password' not in vars(spec)


def test_product_and_limit_results_are_readable_in_progress(monkeypatch):
    auction = Auction()
    messages = []
    auction.auction_operation_signal.connect(messages.append)
    browser = SimpleNamespace(current_url='https://www.auction.co.kr/mock', get=lambda url: None,
        execute_script=lambda *args: {'title': '로컬 경매 상품', 'price': '13,000원', 'bid': True, 'count': '4명'})
    spec = BidTaskSpec(browser.current_url, 0, datetime.now(), 'id', fixed_price=False,
                       max_price=13000, additional_amount=1000)
    auction.load_product(spec, BidTaskRuntime(browser=browser), lambda: False)
    result = BidResult(spec, status='over_limit')
    result.timing.update(latest_price=13000, candidate_price=14000)
    auction.bid_logger = SimpleNamespace(write=lambda event: None)
    auction._report(result)
    assert any('로컬 경매 상품' in s for s in messages)
    assert any('13,000원' in s for s in messages)
    assert any('4명' in s for s in messages)
    assert any('한도 초과' in s for s in messages)
    assert any('PC 입찰 클릭 시각' in s for s in messages)
