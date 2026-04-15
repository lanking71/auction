import threading
import time
import sys
import os

import requests as rq
from selenium.common import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.wait import WebDriverWait
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup as BS

from datetime import datetime
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox
from multiprocessing import Process
import keyboard
import pickle
import undetected_chromedriver as uc
from datetime import datetime
from selenium_stealth import stealth

class Auction(QObject):

    auction_operation_signal = Signal(str)
    auction_bid_results = Signal(list)
    auction_bid_title = Signal(str)
    login_needed_signal = Signal()   # 수동 로그인 필요 → GUI 버튼 활성화

    def __init__(self):
        super().__init__()
        self.local_data = threading.local()
        self._login_event = threading.Event()  # 로그인 완료 대기용
        

    @staticmethod
    def _data_path(filename):
        """개발환경 / PyInstaller exe 양쪽에서 데이터 파일의 절대경로 반환"""
        if getattr(sys, 'frozen', False):
            # PyInstaller exe: exe 파일이 있는 폴더 기준
            base = os.path.dirname(sys.executable)
        else:
            # 개발환경: 프로젝트 루트(CWD) 기준
            base = os.getcwd()
        return os.path.join(base, filename)

    def trigger_manual_login(self):
        """GUI '로그인 완료' 버튼 클릭 또는 자동 감지 시 호출 — 대기 중인 loginstart() 재개"""
        self._login_event.set()

    def check_session_cookies(self):
        try:
            # 저장된 쿠키 로드 (개발환경/exe 모두 호환 경로)
            with open(self._data_path("auction_cookies.pkl"), "rb") as f:
                cookies = pickle.load(f)
            
            # 새로운 세션 생성
            session = rq.Session()
            
            # 쿠키를 세션에 추가
            for cookie in cookies:
                session.cookies.set(
                    name=cookie['name'],
                    value=cookie['value'],
                    domain=cookie.get('domain', '.auction.co.kr')
                )
            
            # 세션 쿠키 확인
            # print("\n=== 세션 쿠키 상태 ===")
            # for cookie in session.cookies:
            #     print(f"{cookie.name}: {cookie.value[:10]}... (길이: {len(cookie.value)})")
                
            return session
            
        except Exception as e:
            print(f"세션 쿠키 확인 중 오류: {e}")
            return None

    def process_task(self,closing_time,interrupted, finished):
        thread_id = threading.get_ident()

        if not hasattr(self.local_data,"thread_data"):
            self.local_data.thread_data = {}

        self.local_data.thread_data[thread_id] = {'closing_time':closing_time,'interrupted':interrupted,'finished':finished}
        self.local_data.thread_data[thread_id]['browser'] = self.setupbrowser()


        if self.loginstart(finished):
            self.startCrawling(interrupted)


    def fixedMultipleBid(self,closing_time,interrupted, finished):
        taskCount = len(closing_time)
        params_list = [(closing_time[i],interrupted,finished) for i in range(taskCount)]
        threads = []

        for params in params_list:
            thread = threading.Thread(target=self.process_task,args=params)
            threads.append(thread)
            thread.start()
            time.sleep(20)

        for thread in threads:
            thread.join()

        if finished:
            finished.emit(False)

        # for params in params_list:
        #     process = Process(target=self.process_task, args=params)
        #     processes.append(process)
        #     process.start()
        #
        # for process in processes:
        #     process.join()



    def auctionStart(self,startData,closing_time,interrupted,finished=None):
        self.fixedplug = False
        self.url = startData[0]
        if len(startData) > 4:
            self.maxPrice = int(startData[1])
            # self.AdditionalAmount = int(startData[2])
            if startData[2].isdigit():
                self.AdditionalAmount = int(startData[2])
            else:
                self.AdditionalAmount = 0
            self.auctionID = startData[3]
            self.auctionPW = startData[4]

            self.closing_time = closing_time[0]
            self.setupbrowser()
            if self.loginstart(finished):
                self.startCrawling(interrupted, finished)
        else:
            self.fixedplug = True
            self.maxPrice = 0
            self.AdditionalAmount = 0
            self.fixedPricelst = [int(item) for item in startData[1] if item != "0"]
            self.auctionID = startData[2]
            self.auctionPW = startData[3]
            closing_timelst = [item for _,item in zip(self.fixedPricelst, closing_time)]

            self.fixedMultipleBid(closing_timelst,interrupted, finished)

    def message_view(self, msg):
        msgstr = QMessageBox()
        msgstr.setWindowTitle("알림")
        msgstr.setText(msg)
        msgstr.exec()

    def setupbrowser(self):
        options = uc.ChromeOptions()
    
        # 기본 설정
        # options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1024,768')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-automation')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-web-security')
        options.add_argument('--allow-running-insecure-content')
        options.add_argument(f'--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        
        
        try:
            self.browser = uc.Chrome(
                options=options,
                use_subprocess=True
            )

            # CDP 명령어로 자동화 감지 우회
            self.browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                '''
            })

            # 기본 설정
            self.browser.set_window_size(1024, 768)
            time.sleep(1)  # 창 크기 적용 대기

            # 페이지 로드 대기 설정
            self.browser.set_page_load_timeout(30)
            self.browser.implicitly_wait(10)
            
            return self.browser
        
        except Exception as e:
            self.auction_operation_signal.emit(f"브라우저 설정 실패: {str(e)}")
            return False
            
    def validate_cookies(self,cookies):
        required_cookies = {
        'auction': None,  # auction 쿠키 추가
        'AGP': None,
        'bcp': None
        }
        
        for cookie in cookies:
            if cookie['name'] in required_cookies:
                required_cookies[cookie['name']] = cookie['value']
        
        return all(required_cookies.values())
    
    def check_cookie_expiry(self,cookies):
        now = datetime.now()
        return all(cookie.get('expiry', now) > now for cookie in cookies)
    
    def save_cookies(self, cookies, filename):
        try:
            if not cookies:
                self.auction_operation_signal.emit("쿠키가 비어있습니다")
                return False

            filepath = self._data_path(filename)
            with open(filepath, "wb") as f:
                pickle.dump(cookies, f)
                
            # 쿠키 적용 로직 개선
            for cookie in cookies:
                try:
                    if 'expiry' in cookie:
                        cookie['expiry'] = int(cookie['expiry'])
                    self.browser.add_cookie(cookie)
                except Exception as e:
                    self.auction_operation_signal.emit(f"쿠키 적용 실패: {cookie['name']}")
                    continue
                    
            return True
        except Exception as e:
            self.auction_operation_signal.emit(f"쿠키 저장 실패: {e}")
            return False
    
    def loginProcess(self,browser):

        import random
    
        try:
            # 명시적 대기 시간 증가
            wait = WebDriverWait(browser, 20)
            
            # 사람처럼 행동하기 위한 랜덤 대기
            time.sleep(random.uniform(2, 4))
            
            # 로그인 버튼 찾기 및 클릭
            login_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.usermenu ul li:first-child a"))
            )
            
            # 마우스 이동 시뮬레이션
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(browser)
            actions.move_to_element(login_button).pause(random.uniform(0.5, 1.5)).click().perform()
            time.sleep(random.uniform(2, 4))
            
            # 아이디 입력 (자연스럽게)
            username = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id='typeMemberInputId']"))
            )
            actions.move_to_element(username).click().perform()
            time.sleep(random.uniform(0.5, 1.0))
            
            # 한 글자씩 입력 (더 자연스럽게)
            for char in self.auctionID:
                username.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            
            time.sleep(random.uniform(0.5, 1.0))

            # 비밀번호 입력
            password = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id='typeMemberInputPassword']"))
            )
            actions.move_to_element(password).click().perform()
            time.sleep(random.uniform(0.5, 1.0))
            
            # 한 글자씩 입력
            for char in self.auctionPW:
                password.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            
            time.sleep(random.uniform(1, 2))

            # 로그인 버튼 클릭
            login_submit = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[id='btnLogin']"))
            )
            actions.move_to_element(login_submit).pause(random.uniform(0.5, 1.0)).click().perform()
            time.sleep(random.uniform(3, 5))

            return self.verify_login(browser)

        except Exception as e:
            self.auction_operation_signal.emit(f"로그인 프로세스 중 오류 발생: {str(e)}")
            return False
    def verify_login(self, browser):
        try:
            # 로그아웃 링크를 직접 찾기
            logout_link = WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='logout']"))
            )
            
            if logout_link and "로그아웃" in logout_link.text:
                self.auction_operation_signal.emit("로그인 상태 확인 완료")
                return True
                
            return False
            
        except (TimeoutException, NoSuchElementException):
            self.auction_operation_signal.emit("로그인 상태가 아닙니다")
            return False
        except Exception as e:
            self.auction_operation_signal.emit(f"로그인 상태 확인 중 오류: {str(e)}")
            return False
        # try:
        #     # 로그아웃 버튼이 있는지 확인하여 로그인 상태 체크
        #     logout_element = WebDriverWait(browser, 5).until(
        #         EC.presence_of_element_located((By.CSS_SELECTOR, "div.usermenu li:nth-child(1) a"))
        #     )
            
        #     if "로그아웃" in logout_element.text:
        #         self.auction_operation_signal.emit("로그인 상태 확인 완료")
        #         return True
                
        #     return False
            
        # except (TimeoutException, NoSuchElementException):
        #     self.auction_operation_signal.emit("로그인 상태가 아닙니다")
        #     return False
        # except Exception as e:
        #     self.auction_operation_signal.emit(f"로그인 상태 확인 중 오류: {str(e)}")
        #     return False
    
    def loginstart(self, finished=None):
        # ── 브라우저 인스턴스 선택 (단일 / 멀티스레드 공용) ──────────────────
        if hasattr(self.local_data, "thread_data"):
            thread_id = threading.get_ident()
            browser = self.local_data.thread_data[thread_id]["browser"]
            self.closing_time = self.local_data.thread_data[thread_id]["closing_time"]
        else:
            browser = self.browser

        if browser is None:
            self.auction_operation_signal.emit("브라우저 초기화에 실패했습니다.")
            if finished:
                finished.emit(False)
            return False

        try:
            # ── 1단계: 옥션 메인 페이지 접속 ───────────────────────────────
            self.auction_operation_signal.emit("옥션 메인 페이지 접속 중...")
            browser.get("http://www.auction.co.kr/")

            # Cloudflare / 보안 검증 페이지 대기 (최대 30초)
            wait_interval = 2
            for elapsed in range(0, 30, wait_interval):
                try:
                    if browser.find_elements(By.CSS_SELECTOR, "div.usermenu"):
                        self.auction_operation_signal.emit("페이지 로딩 완료")
                        break
                    if "사용자 활동 검토" in browser.page_source:
                        self.auction_operation_signal.emit(
                            f"보안 검증 진행 중... ({elapsed}/{30}초) — 브라우저에서 직접 해결해 주세요."
                        )
                except Exception:
                    pass
                time.sleep(wait_interval)

            time.sleep(1)

            # ── 2단계: 기존 세션(쿠키)으로 로그인 여부 확인 ────────────────
            self.auction_operation_signal.emit("기존 세션 확인 중...")
            if self.verify_login(browser):
                self.auction_operation_signal.emit("기존 세션으로 로그인 상태 확인 완료!")
                return True

            # ── 3단계: 수동 로그인 대기 ─────────────────────────────────────
            self._login_event.clear()
            self.auction_operation_signal.emit("━" * 30)
            self.auction_operation_signal.emit("  브라우저에서 직접 로그인해 주세요.")
            self.auction_operation_signal.emit("  로그인 후 자동 감지되거나,")
            self.auction_operation_signal.emit("  [로그인 완료] 버튼을 눌러주세요.")
            self.auction_operation_signal.emit("━" * 30)
            self.login_needed_signal.emit()   # → GUI 버튼 활성화

            # 백그라운드: 2초마다 로그인 상태 자동 감지
            def _poll_login(b):
                while not self._login_event.is_set():
                    time.sleep(2)
                    try:
                        if self.verify_login(b):
                            self.auction_operation_signal.emit("로그인 자동 감지 완료!")
                            self._login_event.set()
                            break
                    except Exception:
                        pass   # 브라우저 닫힘 등 예외는 조용히 무시

            threading.Thread(target=_poll_login, args=(browser,), daemon=True).start()

            # 최대 5분(300초) 대기 — GUI 버튼 또는 자동 감지 시 즉시 해제
            if self._login_event.wait(timeout=300):
                self.auction_operation_signal.emit("로그인 확인 완료! 입찰 준비를 시작합니다...")
                time.sleep(1)   # 페이지 안정화
                return True

            # 타임아웃
            self.auction_operation_signal.emit("로그인 대기 시간 초과 (5분). 다시 시도해주세요.")
            if finished:
                finished.emit(False)
            return False

        except Exception as e:
            import traceback
            error_msg = f"로그인 오류: {str(e)}\n{traceback.format_exc()}"
            self.auction_operation_signal.emit(error_msg)
            if finished:
                finished.emit(False)
            return False

    def bidWindow(self,browser):    
        try:
                # 입찰 버튼이 클릭 가능할 때까지 대기
            bid_button = WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.ID, "ucControls_btn1"))
            )
            
            # 일반 클릭 실행
            bid_button.click()
     
            # 새 창 대기
            WebDriverWait(browser, 10).until(lambda x: len(x.window_handles) > 1)
            handlers = browser.window_handles
            browser.switch_to.window(handlers[1])
            
            return handlers
    
            # # 입찰 버튼 요소 찾기
            # bid_button = WebDriverWait(browser, 10).until(
            #     EC.presence_of_element_located((By.ID, "ucControls_btn1"))
            # )
            
            # # href 속성에서 URL 추출
            # bid_url = bid_button.get_attribute("href")
            # item_no = bid_url.split("itemno=")[1].replace("')", "")
            
            # # 직접 입찰 페이지 URL 열기
            # bid_page_url = f"https://www.auction.co.kr/bid.aspx?itemno={item_no}"
            # browser.execute_script(f"window.open('{bid_page_url}', '_blank')")
            
            # # 새 창으로 전환
            # WebDriverWait(browser, 10).until(lambda x: len(x.window_handles) > 1)
            # handlers = browser.window_handles
            # browser.switch_to.window(handlers[1])
            
            # return handlers
                
        except Exception as e:
            self.auction_operation_signal.emit(f"입찰창 열기 실패: {str(e)}")
            return False
        # script = "document.getElementById('ucControls_btn1').click();"
        # browser.execute_script(script)
        # try:
        #     handlers = browser.window_handles
        #     browser.switch_to.window(handlers[1])
        # except Exception as e:
        #     self.auction_operation_signal.emit(f"입찰을 진행할 수 없는 계정이거나 입찰이 이미 종료되어 오류가 발생하였습니다.")
        #     return False
        # return handlers

    def fixedbid(self,browser):
        button = browser.find_element(By.CSS_SELECTOR,"input#buttonBid")
        browser.execute_script("arguments[0].click();", button)
        # browser.execute_script("document.querySelector('input#buttonBid').click();")

    def refresh(self,browser,last=False):
        browser.refresh()
        if self.refreshError:
            try:
                # 선택자를 미리 변수로 선언
                price_selector = "tbody > tr:nth-of-type(1) > td:nth-of-type(1) > .price" if self.AdditionalAmount > 0 else 'b.name span.price'
                price_element_text = browser.find_element(By.CSS_SELECTOR, price_selector).text
                price_data = int(price_element_text.replace(',', '').replace('원', ''))
                price = price_data + self.AdditionalAmount
                if price <= self.maxPrice:
                    if last:
                        # 필요한 숨겨진 필드들의 값을 가져옵니다.
                        viewstate_value = browser.find_element(By.ID, "__VIEWSTATE").get_attribute('value')
                        eventtarget_value = "buttonBid"  # 폼을 제출하는 버튼의 ID나 이름을 이곳에 설정합니다.
                        eventargument_value = ""  # 추가적인 인수가 필요하면 여기에 값을 설정합니다.

                        combined_script = f"""
                        document.querySelector('#ctrlPrice').value = '{price}';
                        document.querySelector('#__VIEWSTATE').value = '{viewstate_value}';
                        document.querySelector('#__EVENTTARGET').value = '{eventtarget_value}';
                        document.querySelector('#__EVENTARGUMENT').value = '{eventargument_value}';
                        __doPostBack('{eventtarget_value}', '{eventargument_value}');
                        """
                        browser.execute_script(combined_script)
                    else:
                        input_element = WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#ctrlPrice")))
                        input_element.clear()
                else:
                    if not self.fixedplug:
                        self.over_limit = True
            except Exception as e:
                self.refreshError = False
                self.auction_operation_signal.emit(f"입찰 새로고침 에러가 발생했습니다. \n 안전하게 'ALL Chrome Kill' 버튼을 클릭하여 모든 브라우저를 종료한 후 \n '입찰시작' 버튼을 클릭해 주세요.")
                try:
                    error_element = browser.find_element(By.CSS_SELECTOR, "#ErrorMsg")
                    error_message = error_element.text
                    if "이미 낙찰 범위에" in error_message:
                        self.auction_operation_signal.emit("이미 낙찰 범위에 계시기 때문에 입찰하실 수 없습니다.")
                        close_button = browser.find_element(By.CSS_SELECTOR, "#bottombutton img")
                        # close_button.click()
                        browser.execute_script("arguments[0].click();", close_button)
                except:  # 요소를 찾을 수 없는 경우
                    pass

    def bidding(self,browser):
        try:
            alert = browser.switch_to.alert
            alert.accept()
        except:
            pass
        close_button = browser.find_element(By.CSS_SELECTOR, "#bottombutton img")
        # close_button.click()
        browser.execute_script("arguments[0].click();", close_button)


    def biddingPrice(self,soup):
        # 시작가격 추출
        start_price = soup.select_one(".redprice .present_price .present_num").text.replace(',','')
        return int(start_price)

    def competition_ID_check(self,browser):
        auction_record_link = browser.find_element(By.CSS_SELECTOR,"a[href^='javascript:checkEnd']")

        # auction_record_link.click()
        browser.execute_script("arguments[0].click();", auction_record_link)

        bidder_id_element = browser.find_element(By.CSS_SELECTOR,".bid_tbl2 tr:nth-child(2) td.bidid")
        bidder_id_text = bidder_id_element.text

        bidder_time_element = browser.find_element(By.CSS_SELECTOR, ".bid_tbl2 tr:nth-child(2) td:nth-child(2)")
        bidder_time_text = bidder_time_element.text

        # '***' 부분을 제거하여 'lanki' 만 추출합니다.
        bidder_id_clean = bidder_id_text.replace('***', '')
        browser.back()
        return bidder_id_clean,bidder_time_text

    def wait_for_event(self,target_time_str):
        target_time = datetime.strptime(target_time_str, '%y-%m-%d %H:%M:%S.%f')
        return target_time

    def time_difference_calculation(self,new_target_time,now1):
        time_difference = datetime.strptime(new_target_time, '%Y-%m-%d %H:%M:%S.%f')
        time_difference_result = abs((time_difference - now1).total_seconds())

        return time_difference_result

    def check_time(self, target_time,bidprice,handlers,interrupted,browser,interval=0.0001):
        # Windows 타이머 해상도를 1ms로 설정 (기본값 15.6ms → 정밀도 향상)
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
            _timer_period_set = True
        except Exception:
            _timer_period_set = False

        self.refresh(browser)
        try:
            input_element = WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#ctrlPrice")))
            input_element.clear()
        except Exception as e:
            self.auction_operation_signal.emit("입찰금액 입력폼에 문제 발생..")
            if _timer_period_set:
                ctypes.windll.winmm.timeEndPeriod(1)
            return

        def _adaptive_wait(target):
            """남은 시간에 따라 대기 간격을 자동 조절 — CPU 절약 + 정밀도 유지"""
            while True:
                if interrupted():
                    return False
                now = datetime.now()
                remaining = (target - now).total_seconds()
                if remaining <= 0:
                    return True
                elif remaining > 2.0:
                    time.sleep(0.5)       # 2초 이상 남음: 0.5초 단위 대기
                elif remaining > 0.5:
                    time.sleep(0.05)      # 0.5~2초: 50ms 단위 대기
                elif remaining > 0.1:
                    time.sleep(0.005)     # 100~500ms: 5ms 단위 대기
                # 100ms 미만: 무대기 바쁜 루프 (최대 정밀도)

        if self.fixedplug:
            self.auction_operation_signal.emit("고정 금액 입찰입니다..................")
            input_element.send_keys(bidprice)
            fired = _adaptive_wait(target_time)
            if not fired:
                self.auction_operation_signal.emit("작업이 중단되었습니다.")
                if _timer_period_set:
                    ctypes.windll.winmm.timeEndPeriod(1)
                return
            now = datetime.now()
            self.fixedbid(browser)
            end = datetime.now()
            self.bidding(browser)
        else:
            self.auction_operation_signal.emit("일반 자동 입찰입니다...................")
            fired = _adaptive_wait(target_time)
            if not fired:
                self.auction_operation_signal.emit("작업이 중단되었습니다.")
                if _timer_period_set:
                    ctypes.windll.winmm.timeEndPeriod(1)
                return
            now = datetime.now()
            self.refresh(browser,True)
            end = datetime.now()
            self.bidding(browser)

        if _timer_period_set:
            ctypes.windll.winmm.timeEndPeriod(1)

        sec = (end - now)
        result = str(sec)
        browser.switch_to.window(handlers[0])
        click_time = result[6:]
        if self.over_limit:
            self.auction_operation_signal.emit("입찰 금액이 한도를 초과하여서 입찰을 취소합니다.")
            self.auction_bid_results.emit(["한도 초과 : 입찰 취소", target_time, bidprice])
            return
        self.auction_operation_signal.emit(f"마감 설정 시간 : {target_time}")
        self.auction_operation_signal.emit(f"PC 입찰 시간: {now}")
        self.auction_operation_signal.emit(f"입찰 클릭 처리 시간: {end}")

        nameID,bidder_time_text = self.competition_ID_check(browser)
        self.auction_operation_signal.emit(f"옥션 입찰등록 시간 : {bidder_time_text}")
        time_difference_result = self.time_difference_calculation(bidder_time_text,now)
        self.auction_operation_signal.emit(f"옥션 네트워크 지연시간 : {time_difference_result}")
        auctionID = self.auctionID[:-3]
        self.auction_operation_signal.emit(f"TOP1 입찰자 : {nameID} == 내 ID : {auctionID}")
        if nameID == auctionID:
            self.successCheck = True
            self.auction_operation_signal.emit(f"입찰에 성공하였습니다. 입찰금액 : {bidprice}")
            self.auction_bid_results.emit([bidprice, now, bidprice, click_time,time_difference_result,bidder_time_text])
        else:
            self.successCheck = False
            self.auction_operation_signal.emit(f"입찰에 실패하였습니다. 입찰금액 : {bidprice}")
            self.auction_bid_results.emit([bidprice, now, bidprice, click_time, time_difference_result,bidder_time_text])

    def startCrawling(self,interrupted,finished=None):
        if hasattr(self.local_data,"thread_data"):
            thread_id = threading.get_ident()
            browser = self.local_data.thread_data[thread_id]["browser"]
        else:
            browser = self.browser

        browser.get(self.url)
        self.successCheck = False
        self.stop_refresh = False
        self.over_limit = False
        self.refreshError = True

        # 쿠키 세션 준비 — pkl 파일 없을 경우 브라우저 현재 쿠키로 대체
        self.session = self.check_session_cookies()
        if self.session is None:
            self.auction_operation_signal.emit("쿠키 파일 없음 → 현재 브라우저 세션으로 진행합니다.")
            self.session = rq.Session()
            for cookie in browser.get_cookies():
                self.session.cookies.set(
                    name=cookie['name'],
                    value=cookie['value'],
                    domain=cookie.get('domain', '.auction.co.kr')
                )

        try:
            res = self.session.get(self.url)
        except Exception as e:
            self.auction_operation_signal.emit(f"상품 정보 요청 실패: {e}")
            self.cleanup_resources(browser, finished)
            return

        if res.status_code != 200:
            self.auction_operation_signal.emit("URL에 대한 응답이 올바르지 않습니다.")
            return
        soup = BS(res.text,"html.parser")

        try:
            title_txt = soup.select_one("div.titlev3 > h2#hdivItemTitle").text
            self.auction_bid_title.emit(title_txt)
            # 입찰수 추출
            bid_count_text = soup.select_one("dl.nv3 dd span.fss").text
            # 입찰가격 추출
        except:
            self.auction_operation_signal.emit("URL이 올바르지 않습니다.")
            self.cleanup_resources(browser,finished)
            return

        start_price = self.biddingPrice(soup)
        self.auction_operation_signal.emit(f"현재 입찰 가격 : {start_price}")
        if self.fixedplug:
            bidprice = self.fixedPricelst.pop(0)
            self.auction_operation_signal.emit(f"고정 입찰 가격 : {bidprice}")
        else:
            bidprice = start_price + self.AdditionalAmount  # 입찰가격 시작가격
            self.auction_operation_signal.emit(f"신청 입찰 가격 : {bidprice}")

        self.auction_operation_signal.emit(f"입찰자 수 : {bid_count_text}")
        browser.save_screenshot("debug_screenshot.png")
        # 남은시간 추출
        target_time = self.wait_for_event(self.closing_time)
        browser.save_screenshot("debug_screenshot1.png")
        handlers = self.bidWindow(browser)
        browser.save_screenshot("debug_screenshot2.png")
        if handlers:
            thread = threading.Thread(target=self.check_time, args=(target_time,bidprice,handlers,interrupted,browser))
            thread.start()
            thread.join()

        self.cleanup_resources(browser,finished)

    def cleanup_resources(self,browser,finished):
        if self.successCheck:
            self.auction_operation_signal.emit(f"정상 종료 되었습니다..")
        else:
            self.auction_operation_signal.emit(f"입찰이 실패했거나 취소되었습니다. 다시 시작해주세요.")
        try:
            browser.quit()
            self.session.close()
        except Exception as e:
            self.auction_operation_signal.emit(f"종료에러 : {e}")
        if finished:
            finished.emit(False)
