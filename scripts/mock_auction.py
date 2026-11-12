"""Local-only browser test fixture. Never contacts or submits to Auction."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
import json
import time
from urllib.parse import parse_qs

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from browser_runtime import load_browser_bundle


PAGE = r"""<!doctype html><meta charset="utf-8">
<div class="titlev3"><h2 id="hdivItemTitle">Local mock auction</h2></div>
<div class="redprice"><span class="present_price"><span class="present_num">1,000</span></span></div>
<button id="ucControls_btn1" onclick="window.open('/bid','_blank')">Open mock bid</button>
<b class="name"><span class="price">1,000원</span></b>
<table><tbody><tr><td><span class="price">1,000원</span></td></tr></tbody></table>
<input id="ctrlPrice" value="1000"><input id="buttonBid" type="button" value="Mock submit">
<script>
window.mockClicks = [];
function submitMock() {
 const stamp = performance.now();
 let id = window.mockTask;
 if (!id) {
   const fired = Object.values(window.__auctonTimers || {}).find(t=>t.state==='fired' && !t.mockRecorded);
   if (fired) { id = fired.id; fired.mockRecorded = true; }
 }
 id = id || 'normal';
 const t = (window.__auctonTimers || {})[id];
 const row = {id:id, event_ms:stamp, price:Number(document.querySelector('#ctrlPrice').value),
              target_ms:t ? t.target : null};
 mockClicks.push(row);
 fetch('/submit', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(row)});
}
document.querySelector('#buttonBid').onclick = submitMock;
function __doPostBack() { submitMock(); }
</script>"""


@contextmanager
def mock_server():
    class Records(list):
        current_price = 1000
    rows, lock = Records(), Lock()
    rows.login_ids = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith('/login'):
                body = """<meta charset='utf-8'><form method='post' action='/login'>
                <input id='typeMemberInputId' name='id'>
                <input id='typeMemberInputPassword' name='password' type='password'>
                <button id='btnLogin'>Log in</button></form>"""
                if 'error=1' in self.path:
                    body += "<div id='loginError'>Login failed</div>"
                if self.path.startswith('/login-shift'):
                    body = body.replace("<button id='btnLogin'>", "<div id='initial-error' style='height:100px'>기존 안내</div><button id='btnLogin'>")
                    body += """<script>
                    document.querySelector('#typeMemberInputPassword').addEventListener('blur',()=>{
                        document.querySelector('#initial-error').style.height='0px';
                    });</script>"""
            elif self.path.startswith('/challenge'):
                body = "<input id='captcha' value='verification required'>"
            else:
                body = PAGE.replace("1,000", f"{rows.current_price:,}")
                if self.path.startswith('/logged-in'):
                    body += "<a href='/logout'>로그아웃</a>"
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            received = time.perf_counter_ns()
            if self.path == '/login':
                values = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
                user = values.get('id', [''])[0]
                with lock:
                    rows.login_ids.append(user)
                okay = user == 'selected-account' and values.get('password') == ['local-test-password']
                self.send_response(303)
                self.send_header('Location', '/logged-in' if okay else '/login?error=1')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            value["received_ns"] = received
            with lock:
                rows.append(value)
            data = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", rows
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def local_browser():
    bundle = load_browser_bundle()
    options = Options()
    options.binary_location = str(bundle.chrome)
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1024,768")
    browser = webdriver.Chrome(service=Service(str(bundle.driver)), options=options)
    browser.set_page_load_timeout(10)
    browser.set_script_timeout(5)
    return browser
