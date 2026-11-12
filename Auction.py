"""Each task owns its browser from login through submission and cleanup."""
from __future__ import annotations

import json
import re
import threading
import time
import os
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal
from selenium.common.exceptions import NoAlertPresentException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app_paths import data_path
from bid_logging import JsonlBidLogger, sanitize_message, mask_account
from bid_models import BidTaskSpec, BidTaskRuntime, BidResult
from bid_results import parse_record, reconcile
from browser_runtime import create_browser
from auction_login import automatic_login, LoginError
from secure_storage import get_password
from latency import LatencyHistory
from precision_scheduler import (arm_browser_timer, execution_time, monotonic_deadline,
    sample_browser_clock, timer_command, wait_until_ns, windows_precision_window)


STATUS_LABELS = {"accepted": "제출 수락 확인", "unknown": "제출 결과 불명 (내역 확인 필요)",
                 "cancelled": "취소", "expired": "준비/실행 기한 초과", "failed": "실패",
                 "fired": "제출 호출 완료", "over_limit": "한도 초과로 미제출"}


class BatchGate:
    """All tasks must acknowledge readiness/arming before any timer is enabled."""
    def __init__(self, count, deadline_ns):
        self.count, self.deadline_ns = count, deadline_ns
        self.condition = threading.Condition()
        self.arrivals = {"ready": set(), "armed": set()}
        self.error = None

    def abort(self, reason):
        with self.condition:
            self.error = self.error or reason
            self.condition.notify_all()

    def arrive(self, phase, task_id, cancelled):
        with self.condition:
            self.arrivals[phase].add(task_id)
            while not self.error:
                if cancelled():
                    self.error = "batch_cancelled"
                    break
                if time.perf_counter_ns() >= self.deadline_ns:
                    self.error = "batch_preparation_deadline"
                    break
                if len(self.arrivals[phase]) == self.count:
                    self.condition.notify_all()
                    return True
                self.condition.wait(0.02)
            self.condition.notify_all()
            return False


class Auction(QObject):
    auction_operation_signal = Signal(str)
    compensation_updated_signal = Signal(float)
    schedule_updated_signal = Signal(str)
    auction_bid_results = Signal(list)
    auction_bid_title = Signal(str)
    login_needed_signal = Signal()

    def __init__(self):
        super().__init__()
        self.latency_history = LatencyHistory()
        self.bid_logger = JsonlBidLogger()
        self._lock = threading.Lock()
        self._active = {}
        self.last_results = []
        try:
            cfg = json.loads(data_path("config.json").read_text(encoding="utf-8"))
            self.manual_offset_ms = float(cfg.get("manualOffsetMs", 0))
        except (OSError, ValueError, TypeError):
            self.manual_offset_ms = 0.0

    def _message(self, message):
        self.auction_operation_signal.emit(sanitize_message(message))

    def trigger_manual_login(self):
        # A click requests verification; it never asserts another browser is logged in.
        with self._lock:
            for runtime in self._active.values():
                runtime.login_event.set()

    def cancel_all(self):
        with self._lock:
            for runtime in self._active.values():
                runtime.cancel_event.set()

    @staticmethod
    def validate_url(url):
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not (host == "auction.co.kr" or host.endswith(".auction.co.kr"))):
            raise ValueError("HTTPS 옥션 상품 URL만 사용할 수 있습니다.")

    def _specs(self, data, times):
        if data and isinstance(data[0], BidTaskSpec):
            return tuple(data)
        parse = lambda value: datetime.strptime(value, "%y-%m-%d %H:%M:%S.%f")
        if len(data) > 4:
            return (BidTaskSpec(data[0], 0, parse(times[0]), data[3], fixed_price=False,
                    max_price=int(data[1]), additional_amount=int(data[2] or 0)),)
        return tuple(BidTaskSpec(data[0], int(price), parse(target), data[2], self.manual_offset_ms)
                     for price, target in zip(data[1], times) if price and int(price) > 0)

    def auctionStart(self, startData, closing_time, interrupted=lambda: False, finished=None):
        threads = []
        self.last_results = []
        try:
            specs = self._specs(startData, closing_time)
            if not specs or len({s.task_id for s in specs}) != len(specs):
                raise ValueError("유효하고 서로 다른 입찰 작업이 필요합니다.")
            for spec in specs:
                self.validate_url(spec.url)
            if len({s.fixed_price for s in specs}) != 1:
                raise ValueError("한 배치에는 동일 입찰 모드만 사용할 수 있습니다.")
            self.last_results = [BidResult(s) for s in specs]
            self._message(f"입찰 작업 시작: 총 {len(specs)}건")
            runtimes = [BidTaskRuntime() for _ in specs]
            now, mono = datetime.now(), time.perf_counter_ns()
            deadlines = []
            for spec, result in zip(specs, self.last_results):
                automatic = self.latency_history.current_ms("fixed") if spec.fixed_price else 0.0
                manual = spec.manual_offset_ms if spec.fixed_price else 0.0
                local = execution_time(spec.target_server_time, automatic, manual)
                local -= timedelta(milliseconds=spec.server_offset_ms)
                result.automatic_offset_ms, result.applied_offset_ms = automatic, automatic + manual
                wall = now if local.tzinfo is None else now.astimezone(local.tzinfo)
                deadlines.append(monotonic_deadline(local, wall, mono))
                result.timing.update(execution_target=local, deadline_ns=deadlines[-1],
                                     wall_anchor=now, monotonic_anchor_ns=mono,
                                     server_clock_verified=spec.server_uncertainty_ms is not None)
                tag = spec.task_id[:8]
                mode = "고정가" if spec.fixed_price else "일반 자동"
                login_mode = "자동 로그인·창 표시" if spec.automatic_login else "수동 로그인·창 표시"
                self._message(f"[{tag}] {mode} 입찰 / {login_mode}")
                self._message(f"[{tag}] 사용 계정: {mask_account(spec.account_id)}")
                self._message(f"[{tag}] 목표 시각: {spec.target_server_time:%Y-%m-%d %H:%M:%S.%f}")
                if spec.fixed_price:
                    self._message(f"[{tag}] 설정 입찰가: {spec.price:,}원 / 총 보정 {result.applied_offset_ms:.3f}ms")
                else:
                    self._message(f"[{tag}] 금액 한도: {spec.max_price:,}원 / 추가 금액: {spec.additional_amount:,}원")
            # Reserve 300ms before earliest execution for final browser commands.
            gate = BatchGate(len(specs), min(deadlines) - 300_000_000)
            with self._lock:
                self._active = dict(zip((s.task_id for s in specs), runtimes))
            for spec, runtime, result, deadline in zip(specs, runtimes, self.last_results, deadlines):
                thread = threading.Thread(target=self.process_task,
                    args=(spec, runtime, result, deadline, gate, interrupted))
                thread.start()
                threads.append(thread)
            while any(t.is_alive() for t in threads):
                if interrupted():
                    self.cancel_all()
                for thread in threads:
                    thread.join(0.02)
            counts = Counter(r.status for r in self.last_results)
            self._message("작업 종료: " + ", ".join(f"{STATUS_LABELS.get(k, k)} {v}건" for k, v in counts.items()))
        except Exception as exc:
            self.cancel_all()
            for thread in threads:
                thread.join()
            self._message(f"작업 시작 실패: {type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._active.clear()
            if finished:
                finished.emit(False)

    def setupbrowser(self):
        # Each browser now owns a private patchable driver and profile. Starting
        # them serially delays the last bid unnecessarily in multi-window runs.
        browser, degraded = create_browser(self._message, headless=False)
        try:
            browser.set_page_load_timeout(20)
            browser.set_script_timeout(5)
        except Exception:
            browser.quit()
            raise
        self._message("앱 전용 Chrome 시작 완료 (창 표시)"
                      + (" (표준 드라이버)" if degraded else ""))
        return browser, degraded

    def verify_login(self, browser):
        return any("로그아웃" in el.text for el in
                   browser.find_elements(By.CSS_SELECTOR, "a[href*='logout' i]"))

    def loginstart(self, spec, runtime, cancelled, preparation_deadline):
        browser = runtime.browser
        self._message(f"[{spec.task_id[:8]}] 옥션 메인 페이지 접속 중...")
        browser.get("https://www.auction.co.kr/")
        if not spec.automatic_login and self.verify_login(browser):
            self._message(f"[{spec.task_id[:8]}] 로그인 상태 확인 완료")
            return True
        if spec.automatic_login:
            self._message(f"[{spec.task_id[:8]}] 선택 계정으로 자동 로그인 중 (브라우저 창 표시)")
            try:
                password = get_password(spec.account_id)
            except Exception:
                raise LoginError("Windows 저장 비밀번호를 읽지 못했습니다. 계정을 다시 등록하세요.") from None
            try:
                okay = automatic_login(browser, spec.account_id, password, cancelled,
                                       preparation_deadline, self.verify_login,
                                       lambda message: self._message(f"[{spec.task_id[:8]}] {message}"))
            finally:
                del password
            self._message(f"[{spec.task_id[:8]}] 자동 로그인 확인 완료! 입찰 준비를 시작합니다.")
            return okay
        self._message("브라우저에서 직접 로그인해 주세요. 로그인 완료 버튼은 상태를 다시 확인합니다.")
        self.login_needed_signal.emit()
        end = min(time.perf_counter_ns() + 300_000_000_000, preparation_deadline)
        while time.perf_counter_ns() < end and not cancelled():
            if self.verify_login(browser):
                self._message("로그인 확인 완료! 현재 브라우저에서 상품 정보를 읽습니다.")
                return True
            runtime.login_event.wait(0.5)
            runtime.login_event.clear()
        return False

    def load_product(self, spec, runtime, cancelled):
        """Read the authenticated rendered page, never a second HTTP session."""
        if cancelled():
            raise InterruptedError("cancelled")
        browser = runtime.browser
        browser.get(spec.url)
        def product(driver):
            if cancelled():
                raise InterruptedError("cancelled")
            self.validate_url(driver.current_url)
            data = driver.execute_script("""
const title = document.querySelector('div.titlev3 > h2#hdivItemTitle');
const price = document.querySelector('.redprice .present_price .present_num');
const count = document.querySelector('dl.nv3 dd span.fss');
return {title:title ? title.textContent.trim() : '',
        price:price ? price.textContent.trim() : '',
        count:count ? count.textContent.trim() : null,
        bid:!!document.querySelector('#ucControls_btn1')};
""")
            return data if data and data.get("title") and data.get("price") and data.get("bid") else False
        try:
            data = WebDriverWait(browser, 15, poll_frequency=0.2).until(product)
        except InterruptedError:
            raise
        except Exception as exc:
            raise RuntimeError("상품 화면에서 경매 제목·현재가·입찰 버튼을 확인하지 못했습니다. "
                               "상품 URL, 로그인 또는 브라우저의 안내 화면을 확인하세요.") from exc
        self.auction_bid_title.emit(data["title"])
        price = int(re.sub(r"[^0-9]", "", data["price"]))
        self._message(f"[{spec.task_id[:8]}] 상품명: {data['title']}")
        self._message(f"[{spec.task_id[:8]}] 현재 입찰 가격: {price:,}원")
        count = data.get("count")
        self._message(f"[{spec.task_id[:8]}] 입찰자 수: {count if count is not None else '화면에서 확인 불가'}")
        return price

    def read_records(self, browser):
        links = browser.find_elements(By.CSS_SELECTOR, "a[href^='javascript:checkEnd']")
        if not links:
            return None
        browser.execute_script("arguments[0].click();", links[0])
        try:
            WebDriverWait(browser, 3).until(lambda b: b.find_elements(By.CSS_SELECTOR, ".bid_tbl2"))
            rows = browser.execute_script("""
return Array.from(document.querySelectorAll('.bid_tbl2 tr')).map(row => {
 const id = row.querySelector('td.bidid');
 return id ? [id.textContent.trim(), ...Array.from(row.querySelectorAll('td'))
   .filter(td=>td !== id).map(td=>td.textContent.trim())] : [];
});""")
            return [record for cells in rows if (record := parse_record(cells)) is not None]
        finally:
            browser.back()

    def bidWindow(self, browser):
        original, previous = browser.current_window_handle, set(browser.window_handles)
        WebDriverWait(browser, 10).until(lambda b: b.find_element(By.ID, "ucControls_btn1").is_enabled())
        browser.find_element(By.ID, "ucControls_btn1").click()
        WebDriverWait(browser, 10).until(lambda b: set(b.window_handles) - previous)
        popup = next(iter(set(browser.window_handles) - previous))
        browser.switch_to.window(popup)
        WebDriverWait(browser, 10).until(lambda b: b.find_elements(By.CSS_SELECTOR, "#ctrlPrice"))
        self.enable_fast_refresh(browser)
        return original, popup

    def enable_fast_refresh(self, browser):
        # Retain the existing static-resource reduction for normal-mode refresh;
        # never block HTML, CSS or the site's form scripts.
        try:
            browser.execute_cdp_cmd("Network.enable", {})
            browser.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
                "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg", "*.ico",
                "*.woff", "*.woff2", "*.ttf", "*.mp4", "*.webm"]})
        except Exception as exc:
            self._message(f"정적 리소스 차단 미적용: {type(exc).__name__}")

    def process_task(self, spec, runtime, result, deadline_ns, gate, interrupted):
        browser, bridge, handlers, before = None, None, None, None
        cancelled = lambda: runtime.cancel_event.is_set() or interrupted()
        try:
            result.timing["preparation_stage"] = "browser_start"
            if cancelled():
                raise InterruptedError("cancelled")
            if time.perf_counter_ns() >= gate.deadline_ns:
                result.status = "expired"
                return
            runtime.browser, runtime.stealth_degraded = self.setupbrowser()
            browser = runtime.browser
            if cancelled():
                raise InterruptedError("cancelled")
            result.timing["preparation_stage"] = "login"
            if not self.loginstart(spec, runtime, cancelled, gate.deadline_ns):
                result.status = "cancelled" if cancelled() else "expired"
                return
            result.timing["preparation_stage"] = "product"
            self.load_product(spec, runtime, cancelled)
            try:
                before = self.read_records(browser)
            except Exception:
                self._message("제출 전 기록 확인 불가: 이번 시도의 자동 학습을 보류합니다.")
                browser.get(spec.url)
            if cancelled():
                raise InterruptedError("cancelled")
            result.timing["preparation_stage"] = "bid_popup"
            self._message(f"[{spec.task_id[:8]}] 입찰 창을 준비하는 중...")
            handlers = self.bidWindow(browser)
            if spec.fixed_price:
                field = browser.find_element(By.CSS_SELECTOR, "#ctrlPrice")
                field.clear()
                field.send_keys(str(spec.price))
                result.submitted_price = spec.price
                self._message(f"[{spec.task_id[:8]}] 고정 입찰가 {spec.price:,}원 입력 완료")
            runtime.ready_event.set()
            result.timing["preparation_stage"] = "ready"
            result.timing["prepared_ns"] = time.perf_counter_ns()
            self._message(f"[{spec.task_id[:8]}] 입찰 준비 완료. 예약 시각을 확인합니다.")
            if not gate.arrive("ready", spec.task_id, cancelled):
                result.status = "cancelled" if cancelled() else "expired"
                return
            if spec.server_uncertainty_ms is None:
                self._message("서버·PC 시계 차이 미검증: 수동 보정은 유지하며 자동 학습은 보류합니다.")
            self.schedule_updated_signal.emit(
                f"[{spec.task_id[:8]}] 실행 예정 {result.timing['execution_target']:%H:%M:%S.%f} "
                f"/ 보정 {result.applied_offset_ms:.3f}ms")
            if spec.fixed_price:
                result.timing["preparation_stage"] = "clock_sync"
                bridge = sample_browser_clock(browser)
                result.timing.update(clock_uncertainty_ms=bridge.uncertainty_ms,
                                     clock_page=bridge.page, arm_requested_ns=time.perf_counter_ns())
                # Any lost acknowledgement after this point is uncertain. No fallback click.
                runtime.state = result.status = "arming"
                result.timing["preparation_stage"] = "arm"
                ack = arm_browser_timer(browser, deadline_ns, runtime.cancel_event,
                                        task_id=spec.task_id, bridge=bridge)
                result.timing["arm_ack_ns"] = time.perf_counter_ns()
                if ack.get("state") != "armed":
                    runtime.state = ack.get("state", "unknown")
                    result.status = "failed" if runtime.state == "not_armed" else runtime.state
                    return
                runtime.state = result.status = "armed"
                runtime.armed_event.set()
                self._message(f"[{spec.task_id[:8]}] 브라우저 타이머 장전 승인 완료")
                if not gate.arrive("armed", spec.task_id, cancelled):
                    receipt = timer_command(browser, spec.task_id, "cancel")
                    runtime.state = receipt.get("state", "unknown")
                    result.status = runtime.state
                    if runtime.state == "cancelled" and not cancelled():
                        result.status = "expired"
                    result.timing["batch_error"] = gate.error
                    return
                with windows_precision_window():
                    result.timing["preparation_stage"] = "enable"
                    timer_command(browser, spec.task_id, "enable")
                    self._message(f"[{spec.task_id[:8]}] 입찰 대기 중: {result.timing['execution_target']:%H:%M:%S.%f}")
                    result.timing["preparation_stage"] = "wait_receipt"
                    receipt = self._wait_receipt(spec, runtime, bridge, deadline_ns, cancelled)
                result.webdriver_returned_at = datetime.now()
                self._apply_receipt(result, bridge, receipt)
                runtime.state = receipt.get("state", "unknown")
            else:
                result.status = runtime.state = "waiting"
                self._message(f"[{spec.task_id[:8]}] 일반 입찰 대기 중. 목표 시각에 최신 가격을 확인합니다.")
                if cancelled() or time.perf_counter_ns() >= deadline_ns:
                    result.status = "cancelled" if cancelled() else "expired"
                    return
                if not wait_until_ns(deadline_ns, runtime.cancel_event):
                    result.status = "cancelled"
                    return
                result.timing["scheduler_fired_ns"] = time.perf_counter_ns()
                result.scheduler_fired_at = datetime.now()
                bridge = self.refresh(browser, spec, runtime, result, cancelled)
                result.webdriver_returned_at = datetime.now()
            if result.status in {"fired", "unknown"}:
                self._message(f"[{spec.task_id[:8]}] 입찰 제출 후 결과 확인 중...")
                self._collect(spec, runtime, result, handlers, before, bridge)
        except InterruptedError:
            result.status = "cancelled"
        except Exception as exc:
            result.error = sanitize_message(f"{type(exc).__name__}: {exc}")
            result.status = "unknown" if runtime.state in {"arming", "armed", "fired"} else "failed"
            bridge = bridge or getattr(runtime, "clock_bridge", None)
            if browser and runtime.state in {"arming", "armed"}:
                try:
                    receipt = timer_command(browser, spec.task_id, "cancel")
                    if bridge:
                        self._apply_receipt(result, bridge, receipt)
                    runtime.state = receipt.get("state", "unknown")
                except Exception:
                    pass
            if result.status == "unknown" and browser and handlers:
                try:
                    self._collect(spec, runtime, result, handlers, before, bridge)
                except Exception:
                    pass
        finally:
            if browser and runtime.state in {"arming", "armed"}:
                try:
                    if handlers and handlers[1] in browser.window_handles:
                        browser.switch_to.window(handlers[1])
                    receipt = timer_command(browser, spec.task_id, "cancel")
                    if bridge:
                        self._apply_receipt(result, bridge, receipt)
                except Exception:
                    if result.status not in {"accepted", "cancelled", "expired"}:
                        result.status = "unknown"
            if result.status not in {"accepted", "fired"}:
                gate.abort(f"task_{result.status}")
            result.cancelled = result.status == "cancelled"
            runtime.close()
            result.cleanup_errors = list(runtime.cleanup_errors)
            self._report(result)

    def _wait_receipt(self, spec, runtime, bridge, deadline_ns, cancelled):
        end = deadline_ns + 5_000_000_000
        while time.perf_counter_ns() < end:
            receipt = timer_command(runtime.browser, spec.task_id,
                                    "cancel" if cancelled() else "status")
            if receipt.get("state") != "armed":
                return receipt
            if receipt.get("page") != bridge.page:
                return {"state": "unknown", "error": "page_changed"}
            runtime.cancel_event.wait(0.02)
        return {"state": "unknown", "error": "receipt_timeout"}

    @staticmethod
    def _apply_receipt(result, bridge, receipt):
        result.timing["browser_receipt"] = receipt
        if receipt.get("error"):
            result.error = result.error or str(receipt["error"])
        state = receipt.get("state", "unknown")
        if state in {"missing", "not_armed", "arming", "armed"}:
            state = "unknown"
        if result.status != "accepted":
            result.status = state
        if receipt.get("page") == bridge.page:
            if receipt.get("price") is not None:
                result.submitted_price = receipt["price"]
            if "fired" in receipt:
                result.scheduler_fired_at = bridge.wall_at(receipt["fired"])
                result.timing["scheduler_fired_ns"] = bridge.python_time(receipt["fired"])
            if "clicked" in receipt:
                result.browser_clicked_at = bridge.wall_at(receipt["clicked"])
                result.timing["browser_clicked_ns"] = bridge.python_time(receipt["clicked"])

    def refresh(self, browser, spec, runtime, result, cancelled):
        result.timing["refresh_started_ns"] = time.perf_counter_ns()
        browser.refresh()
        result.timing["refresh_completed_ns"] = time.perf_counter_ns()
        WebDriverWait(browser, 5).until(lambda b: b.find_elements(By.CSS_SELECTOR, "#ctrlPrice"))
        bridge = sample_browser_clock(browser)
        runtime.clock_bridge = bridge
        result.timing["clock_uncertainty_ms"] = bridge.uncertainty_ms
        if cancelled():
            raise InterruptedError("cancelled")
        runtime.state, result.status = "fired", "unknown"
        value = browser.execute_script("""
const selector = arguments[0] > 0 ? 'tbody > tr:nth-of-type(1) > td:nth-of-type(1) > .price' : 'b.name span.price';
const priceNode = document.querySelector(selector), input = document.querySelector('#ctrlPrice');
if (!priceNode || !input || typeof __doPostBack !== 'function')
  return {state:'failed', error:'price_or_form_missing'};
const raw = priceNode.textContent.replace(/[,원\\s]/g, '');
if (!/^\\d+$/.test(raw)) return {state:'failed', error:'invalid_price'};
const price = Number(raw) + arguments[0];
if (price > arguments[1]) return {state:'over_limit', price:price, current_price:Number(raw)};
const key = 'aucton.bid.' + arguments[2];
if (sessionStorage.getItem(key)) return {state:'unknown', error:'already_attempted'};
input.value = String(price);
const receipt = {state:'fired', page:String(performance.timeOrigin), clicked:performance.now(), price:price, current_price:Number(raw)};
sessionStorage.setItem(key, JSON.stringify(receipt));
__doPostBack('buttonBid', '');
return receipt;
""", spec.additional_amount, spec.max_price, spec.task_id)
        result.timing["submit_returned_ns"] = time.perf_counter_ns()
        result.timing["candidate_price"] = value.get("price")
        result.timing["latest_price"] = value.get("current_price")
        if value.get("state") == "fired":
            result.submitted_price = value.get("price")
        self._apply_receipt(result, bridge, value)
        if value.get("current_price") is not None and value.get("price") is not None:
            self._message(f"[{spec.task_id[:8]}] 최신 현재가: {value['current_price']:,}원 "
                          f"+ 추가 금액: {spec.additional_amount:,}원")
            self._message(f"[{spec.task_id[:8]}] 계산 입찰가: {value['price']:,}원 "
                          f"/ 금액 한도: {spec.max_price:,}원")
        if result.status == "over_limit":
            self._message(f"[{spec.task_id[:8]}] 입찰가가 한도를 초과해 제출하지 않았습니다.")
        return bridge

    def _collect(self, spec, runtime, result, handlers, before, bridge):
        browser = runtime.browser
        try:
            browser.switch_to.alert.accept()
        except NoAlertPresentException:
            pass
        if bridge:
            try:
                receipt = timer_command(browser, spec.task_id)
                if receipt.get("clicked") is not None:
                    self._apply_receipt(result, bridge, receipt)
            except Exception:
                pass
        close = browser.find_elements(By.CSS_SELECTOR, "#bottombutton img")
        if close:
            browser.execute_script("arguments[0].click();", close[0])
        browser.switch_to.window(handlers[0])
        after = self.read_records(browser)
        if after:
            top = after[0]
            result.observations = [{"top_price": top.price, "top_registered_at": top.registered_at}]
            self._message(f"[{spec.task_id[:8]}] 현재 최상위 입찰가: {top.price:,}원 "
                          f"/ 해당 기록의 서버 등록시각: {top.registered_at:%H:%M:%S.%f} (이번 제출 확정 아님)")
        if after is None or before is None:
            self._message(f"[{spec.task_id[:8]}] 제출 전후 입찰 기록을 확인하지 못해 수락 판정을 보류합니다.")
            result.status = "unknown"
            return
        verdict = reconcile(before, after, account_id=spec.account_id,
            price=result.submitted_price, clicked=result.browser_clicked_at,
            returned=datetime.now(), server_offset_ms=spec.server_offset_ms,
            server_uncertainty_ms=(None if self._wall_clock_changed(result) else spec.server_uncertainty_ms))
        result.accepted, result.current_rank = verdict["accepted"], verdict["rank"]
        result.success = result.accepted is True
        result.status = "accepted" if result.success else "unknown"
        row = verdict["record"]
        if row:
            result.server_registered_at = row.registered_at
            delay = (row.registered_at - result.browser_clicked_at).total_seconds() * 1000 - spec.server_offset_ms
            result.timing["raw_server_delay_ms"] = delay
            uncertainty = bridge.uncertainty_ms + spec.server_uncertainty_ms + row.precision_ms
            if self.latency_history.record(delay, success=True,
                mode="fixed" if spec.fixed_price else "normal", task_id=spec.task_id,
                verified=True, uncertainty_ms=uncertainty, evidence=verdict["evidence"]):
                self.compensation_updated_signal.emit(self.latency_history.current_ms("fixed"))

    def _report(self, result):
        # Serialization/file I/O occurs only after collection and cleanup.
        tag = result.task.task_id[:8]
        self._message(f"[{tag}] 입찰 결과: {STATUS_LABELS.get(result.status, result.status)}"
                      + (f": {result.error}" if result.error else ""))
        price = f"{result.submitted_price:,}원" if result.submitted_price is not None else "미제출"
        self._message(f"[{tag}] 제출 금액: {price}")
        clicked = result.browser_clicked_at
        self._message(f"[{tag}] PC 입찰 클릭 시각: {clicked.strftime('%Y-%m-%d %H:%M:%S.%f') if clicked else '확인 불가'}")
        registered = result.server_registered_at
        self._message(f"[{tag}] 이번 제출의 서버 등록시각: {registered if registered else '미확인'}")
        delay = result.timing.get("raw_server_delay_ms")
        self._message(f"[{tag}] 클릭 → 서버 등록 지연: {f'{delay:.3f}ms' if delay is not None else '미검증'}")
        if result.current_rank is not None:
            self._message(f"[{tag}] 현재 확인 순위: {result.current_rank}위")
        if result.status == "unknown":
            self._message("제출 결과 불명: 재클릭하지 않았습니다. 옥션 입찰 내역을 확인하세요.")
        if result.status == "expired":
            receipt = result.timing.get("browser_receipt", {})
            reason = receipt.get("error", result.timing.get("batch_error", "preparation_deadline"))
            text = {"not_enabled_before_deadline": "장전 활성화가 목표시각까지 완료되지 않음",
                    "late_fire": "브라우저 타이머의 지각 허용시간 초과",
                    "preparation_deadline": "입찰 준비시간 부족",
                    "batch_preparation_deadline": "전체 작업의 준비·장전시간 부족"}.get(reason, reason)
            self._message(f"[{result.task.task_id[:8]}] 미제출 사유: {text} "
                          f"/ 단계: {result.timing.get('preparation_stage', 'unknown')}")
        self.auction_bid_results.emit([result.status, result.browser_clicked_at,
            result.submitted_price, result.current_rank, result.timing.get("raw_server_delay_ms"),
            result.server_registered_at])
        try:
            self.bid_logger.write({"event": "bid_result", "task_id": result.task.task_id,
                "process_id": os.getpid(),
                "account_id": result.task.account_id, "mode": "fixed" if result.task.fixed_price else "normal",
                "login_mode": "automatic" if result.task.automatic_login else "manual",
                "target_server_time": result.task.target_server_time, "price": result.submitted_price,
                "server_offset_ms": result.task.server_offset_ms,
                "server_uncertainty_ms": result.task.server_uncertainty_ms,
                "status": result.status, "accepted": result.accepted, "rank": result.current_rank,
                "automatic_offset_ms": result.automatic_offset_ms, "applied_offset_ms": result.applied_offset_ms,
                "browser_clicked_at": result.browser_clicked_at, "webdriver_returned_at": result.webdriver_returned_at,
                "server_registered_at": result.server_registered_at, "timing": result.timing,
                "error": result.error, "cleanup_errors": result.cleanup_errors})
        except OSError as exc:
            self._message(f"결과 로그 저장 실패: {type(exc).__name__}")

    @staticmethod
    def _wall_clock_changed(result):
        anchor = result.timing.get("wall_anchor")
        mono = result.timing.get("monotonic_anchor_ns")
        if anchor is None or mono is None:
            return True
        expected = anchor + timedelta(microseconds=(time.perf_counter_ns() - mono) / 1000)
        delta = (datetime.now() - expected).total_seconds() * 1000
        result.timing["wall_clock_change_ms"] = delta
        return abs(delta) > 1.0
