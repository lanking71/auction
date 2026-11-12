"""One selected-account login only. No product navigation or bidding.

Requires --submit-selected explicitly. Reports classifications/booleans only;
never captures credentials, input values, cookies, HTML or screenshots.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_runtime import create_browser
from auction_login import automatic_login, safe_location, LoginError
from secure_storage import get_password


STATE_SCRIPT = r"""
const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
const text = document.body ? document.body.innerText : '';
const codes = [];
for (const [code, pattern] of [
 ['invalid_credentials', /아이디\s*또는\s*비밀번호|아이디와\s*비밀번호.*일치|아이디.*비밀번호.*확인|비밀번호.*틀|비밀번호.*잘못/],
 ['required_id', /아이디를\s*입력/],
 ['required_password', /비밀번호를\s*입력/],
 ['account_locked', /로그인.*제한|계정.*잠|시도.*초과/],
 ['extra_verification', /추가\s*인증.*필요|본인\s*확인.*필요|인증번호.*입력/],
 ['bot_check', /간단한 봇 확인 절차|원활한 서비스 이용을 위한 간단한 확인 안내|Just a moment/i]
]) if(pattern.test(text)) codes.push(code);
const controls = Array.from(document.querySelectorAll('a,button,input[type=button],input[type=submit]'));
const logout = controls.filter(e => (e.innerText || e.value || '').replace(/\s/g,'') === '로그아웃');
return {codes:codes,
 diagnostics:window.__loginDiag||null,
 form_action:(()=>{const f=document.forms.namedItem('form');return f?new URL(f.action).pathname:null})(),
 visible_alerts:Array.from(document.querySelectorAll('[role=alert],.text__input-error')).filter(visible).map(e=>({id:e.id,invalid_credentials:/아이디.*비밀번호.*잘못|아이디.*비밀번호.*확인|일치하지/.test(e.innerText),required_id:/아이디를.*입력/.test(e.innerText),required_password:/비밀번호를.*입력/.test(e.innerText)})),
 id_present:!!(document.querySelector('#typeMemberInputId')||{}).value,
 password_present:!!(document.querySelector('#typeMemberInputPassword')||{}).value,
 login_form_visible:visible(document.querySelector('#typeMemberInputId')),
 login_button_enabled:!!document.querySelector('#btnLogin:not(:disabled)'),
 captcha_visible:Array.from(document.querySelectorAll('input[id*=captcha i],iframe[src*=captcha i]')).some(visible),
 new_device_visible:['btn_reg__new-device','btn_ignore__new-device'].some(id=>visible(document.getElementById(id))),
 logout_control_count:logout.length, logout_visible_count:logout.filter(visible).length,
 legacy_logout_count:Array.from(document.querySelectorAll('a[href*="logout" i]')).filter(e=>visible(e)&&e.innerText.includes('로그아웃')).length,
 logout_control_tags:logout.filter(visible).map(e=>e.tagName.toLowerCase())};
"""


def network_location(url):
    parsed = urlparse(url)
    if parsed.hostname in ('signin.auction.co.kr', 'memberssl.auction.co.kr') and parsed.path.lower().startswith('/authenticate/'):
        return safe_location(url)
    return f'{parsed.scheme}://{parsed.hostname or ""}' + ('/' if parsed.path == '/' else '/[resource]')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-dir', required=True)
    parser.add_argument('--submit-selected', action='store_true')
    args = parser.parse_args()
    if not args.submit_selected:
        parser.error('Explicit --submit-selected is required')
    root = Path(args.runtime_dir)
    config = json.loads((root/'config.json').read_text(encoding='utf-8'))
    rows = json.loads((root/'account_data.json').read_text(encoding='utf-8'))
    account = config.get('auctionID', '')
    if not account or account not in {row.get('id') for row in rows}:
        raise SystemExit('Selected account is not registered')
    folder = Path('build/login-response-inspection')
    folder.mkdir(parents=True, exist_ok=True)
    report = {'login_only': True, 'bid_attempted': False, 'snapshots': [], 'network': [], 'js_errors': []}
    browser = None
    password = None
    start = time.perf_counter()
    def drain_logs(driver):
        import re
        for row in driver.get_log('performance'):
            event = json.loads(row['message'])['message']
            params = event.get('params', {})
            method = event.get('method')
            if method == 'Network.requestWillBeSent' and params.get('request', {}).get('method') == 'POST':
                report['network'].append({'event':'post', 'location':network_location(params['request']['url'])})
            elif method == 'Network.responseReceived':
                response = params.get('response', {})
                report['network'].append({'event':'response','location':network_location(response.get('url','')),
                                          'status':response.get('status')})
            elif method == 'Network.loadingFailed':
                error = re.search(r'net::[A-Z_]+', params.get('errorText',''))
                report['network'].append({'event':'load_error','code':error.group(0) if error else 'network_error'})
        for row in driver.get_log('browser'):
            if row.get('level') == 'SEVERE':
                message = row.get('message','')
                category = next((t for t in ['ReferenceError','TypeError','SyntaxError','ERR_'] if t in message),'script_or_resource_error')
                report['js_errors'].append(category)
    def progress(message):
        if '입력 화면 확인 완료' in message:
            browser.execute_script("""
window.__loginDiag={clicks:[],submits:0,invalid:[],errors:[],pagehide:0};
document.addEventListener('click',e=>{if(e.target.closest('#btnLogin')) __loginDiag.clicks.push({trusted:e.isTrusted,target:e.target.tagName})},true);
document.addEventListener('submit',()=>__loginDiag.submits++,true);
document.addEventListener('invalid',e=>__loginDiag.invalid.push(e.target.id),true);
window.addEventListener('error',e=>__loginDiag.errors.push(e.error?e.error.name:'resource_error'));
window.addEventListener('pagehide',()=>__loginDiag.pagehide++);
""")
        if '1회' in message:
            report['before_submit'] = browser.execute_script(STATE_SCRIPT)
            # Discard pre-login page load logs; never persist raw log events.
            browser.get_log('performance')
            browser.get_log('browser')
    def observe(driver):
        drain_logs(driver)
        passed = False
        original = driver.current_window_handle
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            parsed = urlparse(driver.current_url)
            if not ((parsed.hostname or '') == 'auction.co.kr' or (parsed.hostname or '').endswith('.auction.co.kr')):
                continue
            state = driver.execute_script(STATE_SCRIPT)
            state['location'] = safe_location(driver.current_url)
            state['elapsed_seconds'] = round(time.perf_counter()-start, 2)
            state['windows'] = len(driver.window_handles)
            if not report['snapshots'] or state['elapsed_seconds'] - report['snapshots'][-1]['elapsed_seconds'] >= 1:
                report['snapshots'].append(state)
            if state['logout_visible_count']:
                report['verified_logout_control'] = state
                passed = True
                break
        if not passed and original in driver.window_handles:
            driver.switch_to.window(original)
        return passed
    try:
        password = get_password(account)
        report['saved_credential_available'] = bool(password)
        if password:
            browser, degraded = create_browser(headless=True, diagnostic_logging=True)
            browser.set_page_load_timeout(20)
            browser.set_script_timeout(5)
            report['standard_fallback'] = degraded
            browser.get('https://www.auction.co.kr/')
            report['login_confirmed'] = automatic_login(browser, account, password,
                lambda: False, time.perf_counter_ns()+35_000_000_000, observe, progress)
        else:
            report['login_confirmed'] = False
            report['error'] = 'saved_credential_not_available_in_test_context'
    except Exception as exc:
        report['login_confirmed'] = False
        report['error_type'] = type(exc).__name__
        if isinstance(exc, LoginError):
            report['error'] = str(exc)
        if browser:
            try:
                observe(browser)
            except Exception:
                pass
    finally:
        password = None
        if browser:
            browser.quit()
    (folder/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('snapshots','network')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
