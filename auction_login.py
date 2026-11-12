"""Normal login form submission; never bypass challenges or log credentials."""
from __future__ import annotations
import time
from urllib.parse import urlparse
from selenium.webdriver.common.by import By

LOGIN_URL = "https://signin.auction.co.kr/Authenticate/Login.aspx?url=https%3A%2F%2Fwww.auction.co.kr%2F"


class LoginError(RuntimeError):
    pass


class LoginChallengeError(LoginError):
    pass


def safe_location(url):
    parsed = urlparse(url)
    return f'{parsed.scheme}://{parsed.hostname or ""}{parsed.path}'


def validate_login_origin(url):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "signin.auction.co.kr"
        or parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise LoginError(f"옥션 로그인 화면이 아닌 페이지로 이동했습니다 ({safe_location(url)}). 수동 로그인을 선택하세요.")


def _check_challenge(browser, *, after_submit=False):
    for element in browser.find_elements(By.CSS_SELECTOR,
            "iframe[src*='captcha'], input[id*='captcha' i], input[autocomplete='one-time-code']"):
        if element.is_displayed():
            raise LoginChallengeError("추가 인증·보안문자가 필요합니다. 수동 로그인으로 다시 시작하세요.")
    if not after_submit:
        return  # An old validation message on an untouched form is not a failed attempt.
    for element in browser.find_elements(By.CSS_SELECTOR, "#ErrorMsg, #loginError, .error-message, [role='alert']"):
        if element.is_displayed() and element.text.strip():
            # Do not echo server messages, form values or Selenium parameters.
            raise LoginError("자동 로그인 인증이 완료되지 않았습니다. 계정 정보를 확인하거나 수동 로그인을 선택하세요.")


def _is_bot_check(browser):
    return bool(browser.execute_script("""
const text = document.body ? document.body.innerText : '';
const form = document.querySelector('#typeMemberInputId');
return !form && (!!document.querySelector('input[name="cf-turnstile-response"], #challenge-running, #cf-challenge-running')
    || /간단한 봇 확인 절차|원활한 서비스 이용을 위한 간단한 확인 안내|Checking your browser|Just a moment/i.test(text));
"""))


def prepare_login_form(browser, cancelled, deadline_ns, progress=None):
    """Navigate and validate the live form without reading or entering secrets."""
    notify = progress or (lambda message: None)
    if cancelled():
        raise InterruptedError('cancelled')
    notify('현재 옥션 로그인 주소에 접속합니다.')
    browser.get(LOGIN_URL)
    bot_started = None
    while time.perf_counter_ns() < deadline_ns:
        if cancelled():
            raise InterruptedError('cancelled')
        _check_challenge(browser)
        if _is_bot_check(browser):
            if bot_started is None:
                bot_started = time.perf_counter_ns()
                notify('옥션의 브라우저 확인 페이지를 기다리는 중입니다.')
            if time.perf_counter_ns() - bot_started >= 8_000_000_000:
                raise LoginChallengeError('옥션 브라우저 확인이 완료되지 않았습니다. 표시된 창을 확인하거나 수동 로그인을 선택하세요.')
            time.sleep(.2)
            continue
        validate_login_origin(browser.current_url)
        ids = browser.find_elements(By.CSS_SELECTOR, '#typeMemberInputId')
        passwords = browser.find_elements(By.CSS_SELECTOR, '#typeMemberInputPassword')
        buttons = browser.find_elements(By.CSS_SELECTOR, '#btnLogin')
        if (ids and passwords and buttons and ids[0].is_displayed()
            and passwords[0].is_displayed() and buttons[0].is_displayed()):
            notify('옥션 로그인 입력 화면 확인 완료.')
            return ids[0], passwords[0], buttons[0]
        time.sleep(.1)
    raise LoginError(f'로그인 입력 화면 준비 시간이 초과되었습니다 ({safe_location(browser.current_url)}). 수동 로그인을 선택하세요.')


def _settle_login_button(browser, button, cancelled, deadline_ns):
    """Finish field blur/layout changes before the single native pointer click.

    The live form removes its initial error on password focusout. Letting the
    pointer's mousedown do that moves the button before mouseup, losing the click.
    Focus is ordinary UI interaction; do not replace the site's submit handler.
    """
    if cancelled():
        raise InterruptedError('cancelled')
    focused = browser.execute_script('arguments[0].focus(); return document.activeElement === arguments[0]', button)
    if not focused:
        raise LoginError('로그인 버튼으로 포커스를 옮기지 못했습니다. 제출하지 않았습니다. 수동 로그인을 선택하세요.')
    end = min(deadline_ns, time.perf_counter_ns() + 2_000_000_000)
    previous, stable_since = None, None
    while time.perf_counter_ns() < end:
        if cancelled():
            raise InterruptedError('cancelled')
        buttons = browser.find_elements(By.CSS_SELECTOR, '#btnLogin')
        current = buttons[0] if buttons else None
        if current and current.is_displayed() and current.is_enabled():
            rect = current.rect
            position = tuple(round(rect[key], 1) for key in ('x', 'y', 'width', 'height'))
            now = time.perf_counter_ns()
            if position != previous:
                previous, stable_since = position, now
            elif now - stable_since >= 150_000_000:
                return current
        else:
            previous, stable_since = None, None
        time.sleep(.05)
    raise LoginError('로그인 버튼 위치가 안정되지 않았습니다. 제출하지 않았습니다. 수동 로그인을 선택하세요.')


def automatic_login(browser, account_id, password, cancelled, deadline_ns, verify_login, progress=None):
    """Submit once, verify logout state, and fail closed on challenges/errors."""
    if not account_id or not password:
        raise LoginError("선택 계정의 저장 비밀번호가 없습니다. 계정 등록에서 비밀번호를 저장하세요.")
    end = min(deadline_ns, time.perf_counter_ns() + 30_000_000_000)
    try:
        username, password_input, button = prepare_login_form(browser, cancelled, end, progress)
        if cancelled():
            raise InterruptedError('cancelled')
        validate_login_origin(browser.current_url)
        username.clear()
        username.send_keys(account_id)
        password_input.clear()
        password_input.send_keys(password)
        button = _settle_login_button(browser, button, cancelled, end)
        if cancelled():
            raise InterruptedError('cancelled')
        if progress:
            progress('선택 계정의 로그인 버튼을 1회 누릅니다.')
        # One submit attempt only, even if its response is lost.
        button.click()
        bot_started = None
        while time.perf_counter_ns() < end:
            if cancelled():
                raise InterruptedError("cancelled")
            if verify_login(browser):
                return True
            _check_challenge(browser, after_submit=True)
            if _is_bot_check(browser):
                if bot_started is None:
                    bot_started = time.perf_counter_ns()
                    if progress:
                        progress('로그인 응답의 브라우저 확인을 기다리는 중입니다.')
                if time.perf_counter_ns() - bot_started >= 8_000_000_000:
                    raise LoginChallengeError('로그인 후 옥션 봇 확인이 완료되지 않았습니다. 수동 로그인으로 확인하세요.')
            else:
                bot_started = None
            time.sleep(.1)
    except (LoginError, InterruptedError):
        raise
    except Exception as exc:
        raise LoginError(f"자동 로그인 화면 처리 실패 ({type(exc).__name__}). 수동 로그인으로 다시 시작하세요.") from None
    raise LoginError("자동 로그인 확인 시간이 초과되었습니다. 수동 로그인으로 다시 시작하세요.")
