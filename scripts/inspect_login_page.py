"""Login routing/DOM inspection in a fresh headless browser.

No stored account or credentials are used. Optional synthetic input probes keep
one credential field empty before clicks; they cannot authenticate an account.
"""
import json
from pathlib import Path
import sys
import time
import argparse
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_runtime import create_browser
from auction_login import LOGIN_URL, prepare_login_form


def location(url):
    parsed = urlparse(url)
    return f'{parsed.scheme}://{parsed.netloc}{parsed.path}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--validate-empty', action='store_true')
    parser.add_argument('--web-login-link', action='store_true')
    parser.add_argument('--type-probe', action='store_true')
    parser.add_argument('--focus-click-probe', action='store_true')
    args = parser.parse_args()
    folder = Path('build/login-inspection')
    folder.mkdir(parents=True, exist_ok=True)
    browser, degraded = create_browser(headless=True)
    browser.set_page_load_timeout(20)
    browser.set_script_timeout(5)
    report = {'headless': True, 'standard_fallback': degraded, 'pages': []}
    try:
        if args.prepare_only:
            messages = []
            try:
                elements = prepare_login_form(browser, lambda: False,
                    time.perf_counter_ns()+30_000_000_000, messages.append)
                if args.web_login_link:
                    link = browser.execute_script("""
return Array.from(document.querySelectorAll('a[href]')).filter(e=>e.textContent.trim()==='로그인')
 .map(e=>e.href).find(h=>new URL(h).hostname==='memberssl.auction.co.kr') || null;
""")
                    report['web_entry_found'] = bool(link)
                    if link:
                        browser.get(link)
                        time.sleep(2)
                        report['web_entry_location'] = location(browser.current_url)
                        fields = [browser.find_elements('css selector', s) for s in
                                  ['#typeMemberInputId', '#typeMemberInputPassword', '#btnLogin']]
                        elements = tuple(f[0] for f in fields) if all(fields) else ()
                report['form_ready'] = len(elements) == 3 and all(e.is_displayed() for e in elements)
                report['field_ids'] = [e.get_attribute('id') for e in elements]
                if args.type_probe:
                    # Synthetic values only; never click or submit this probe.
                    if not args.focus_click_probe:
                        elements[0].send_keys('local-form-probe')
                    elements[1].send_keys('local-form-probe')
                    report['typed_form'] = browser.execute_script("""
const b=document.querySelector('#btnLogin'), r=b.getBoundingClientRect();
const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
return {buttonTag:b.tagName,buttonType:b.type,onclick:b.getAttribute('onclick'),
 buttonEnabled:!b.disabled,hitTag:hit&&hit.tagName,hitId:hit&&hit.id,
 submitFunction:typeof window.submitLoginMember==='function'?String(window.submitLoginMember).slice(0,20000):null,
 activeId:document.activeElement.id,
 idFields:document.querySelectorAll('#typeMemberInputId').length,
 passwordFields:document.querySelectorAll('#typeMemberInputPassword').length,
 formFields:Array.from(document.forms).map(f=>({name:f.name,id:f.getAttribute('id'),
 idPresent:!!(f.elements.namedItem('id')||{}).value,
 passwordPresent:!!(f.elements.namedItem('password')||{}).value})),
 alerts:Array.from(document.querySelectorAll('[role=alert],.text__input-error')).filter(e=>e.getClientRects().length).map(e=>({id:e.id,classes:e.className})),
 events:window.jQuery&&jQuery._data?Object.keys(jQuery._data(b,'events')||{}):[]};
""")
                    if args.focus_click_probe:
                        # Empty username: validation only, no authentication.
                        assert not elements[0].get_attribute('value')
                        browser.execute_script("""
window.__probeClicks=[];
for(const t of ['mousedown','mouseup','click']) document.addEventListener(t,e=>{
const b=document.querySelector('#btnLogin'),r=b.getBoundingClientRect();
__probeClicks.push({event:t,onButton:!!e.target.closest('#btnLogin'),buttonY:r.y});},true);
""")
                        elements[2].click()
                        report['focused_click'] = browser.execute_script('return window.__probeClicks')
                        browser.execute_script('window.__probeClicks=[]')
                        browser.execute_script('arguments[0].focus()', elements[2])
                        time.sleep(.3)
                        elements[2].click()
                        report['blurred_click'] = browser.execute_script('return window.__probeClicks')
                report['public_form_behavior'] = browser.execute_script("""
const b=document.querySelector('#btnLogin');
const jq=window.jQuery;
let direct=[], delegated=[];
if(jq && jq._data) {
  direct=((jq._data(b,'events')||{}).click||[]).map(h=>String(h.handler).slice(0,2500));
  delegated=((jq._data(document,'events')||{}).click||[]).filter(h=>(h.selector||'').includes('btnLogin'))
    .map(h=>String(h.handler).slice(0,2500));
}
return {ready:document.readyState,jquery:typeof jq,
 app_mode:typeof window.isApp==='boolean'?window.isApp:null,
 token_mode:typeof window.tokenEnable==='boolean'?window.tokenEnable:null,
 submitFunction:typeof window.submitLoginMember==='function'?String(window.submitLoginMember).slice(0,20000):null,
 passwordReader:typeof window.GetPwdValue_K==='function'?String(window.GetPwdValue_K).slice(0,14000):null,
 validationFunction:window.App&&typeof App.loginFormValidateCheck==='function'?String(App.loginFormValidateCheck).slice(0,5000):null,
 passwordEventAttributes:Array.from(document.querySelector('#typeMemberInputPassword').attributes).filter(a=>a.name.startsWith('on')).map(a=>({name:a.name,code:a.value})),
 onclick:b?b.getAttribute('onclick'):null,direct:direct,delegated:delegated,
 form:b&&b.form?{id:b.form.getAttribute('id'),action:new URL(b.form.getAttribute('action')||location.href,location.href).origin+new URL(b.form.getAttribute('action')||location.href,location.href).pathname}:null,
 scriptPaths:Array.from(document.scripts).filter(s=>s.src).map(s=>new URL(s.src).origin+new URL(s.src).pathname)};
""")
                if args.validate_empty:
                    empty = browser.execute_script("return !document.querySelector('#typeMemberInputId').value && !document.querySelector('#typeMemberInputPassword').value")
                    if not empty:
                        raise RuntimeError('Expected an untouched empty form')
                    elements[2].click()
                    time.sleep(.2)
                    report['empty_validation'] = browser.execute_script("""
const visible=e=>!!(e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
return {required_id:/아이디.*입력/.test(document.body.innerText),
 alerts:Array.from(document.querySelectorAll('[role=alert]')).filter(visible).map(e=>({id:e.id,classes:e.className})),
 invalid_inputs:Array.from(document.querySelectorAll('input[aria-invalid=true]')).map(e=>e.id)};
""")
                # This is a fresh, untouched login form. No credentials or form
                # values have been read/entered; retain only JS failure categories.
                report['console_errors'] = []
                for entry in browser.get_log('browser'):
                    message = entry.get('message', '')
                    if entry.get('level') == 'SEVERE':
                        import re
                        urls = re.findall(r'https?://[^\s\"<>]+', message)
                        report['console_errors'].append({
                            'category': next((c for c in ['ReferenceError','TypeError','SyntaxError','ERR_NAME_NOT_RESOLVED','ERR_BLOCKED_BY_CLIENT','ERR_CONNECTION','CORS'] if c in message), 'resource_error'),
                            'paths': [location(u) for u in urls]})
            except Exception as exc:
                report['form_ready'] = False
                report['error'] = str(exc)
            report['url'] = location(browser.current_url)
            report['messages'] = messages
            (folder/'prepared-form.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            browser.save_screenshot(str(folder/'prepared-form.png'))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        for name, url in [('home', 'https://www.auction.co.kr/'), ('configured-login', LOGIN_URL),
                          ('ssl-login', 'https://signinssl.auction.co.kr/Authenticate/Default.aspx'),
                          ('login-form', 'https://signin.auction.co.kr/Authenticate/Login.aspx')]:
            item = {'name': name, 'requested': location(url)}
            try:
                browser.get(url)
                # Allow ordinary page redirects/verification to complete. No
                # challenge interaction, credentials or form submission.
                time.sleep(5)
                item.update(url=location(browser.current_url), title=browser.title)
                item['structure'] = browser.execute_script("""
return {
 inputs:Array.from(document.querySelectorAll('input')).map(e=>({id:e.id,name:e.name,type:e.type})),
 buttons:Array.from(document.querySelectorAll('button,input[type=submit]')).map(e=>({id:e.id,type:e.type})),
 loginLinks:Array.from(document.querySelectorAll('a[href]')).filter(e=>
    /signin|login|authenticate/i.test(e.href) || e.textContent.trim()==='로그인')
    .map(e=>({text:e.textContent.trim().slice(0,30), origin:new URL(e.href).origin, path:new URL(e.href).pathname})),
 frames:Array.from(document.querySelectorAll('iframe')).map(e=>({id:e.id,src:e.src?new URL(e.src).origin+new URL(e.src).pathname:''})),
 challenge: /사용자 활동 검토|Access Denied|보안문자/.test(document.body.innerText)
};""")
                browser.save_screenshot(str(folder/f'{name}.png'))
            except Exception as exc:
                item['error'] = type(exc).__name__
                item['url'] = location(browser.current_url)
            report['pages'].append(item)
    finally:
        browser.quit()
    (folder/'routing.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
