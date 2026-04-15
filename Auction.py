# ============================================================
# Auction.py — 옥션 자동입찰 핵심 로직
# ============================================================
# 이 파일이 하는 일을 한 줄로 설명하면:
#   "크롬 브라우저를 대신 조종해서, 정해진 시각에 자동으로 입찰 버튼을 눌러준다"
#
# 비유: 내가 직접 경매장에 가지 않아도, 로봇 직원이 정확한 시각에
#       가격표를 들고 손을 번쩍 들어주는 것과 같습니다.
# ============================================================

# ── 필요한 도구들을 가져오는 구역 ──────────────────────────────────────────
import threading       # 여러 일을 동시에 할 수 있게 해주는 도구 (멀티스레딩)
                       # 비유: 주방에 요리사가 여러 명인 것처럼, 여러 입찰을 동시에 진행
import time            # 시간 관련 기능 (잠시 기다리기 등)
import sys             # 프로그램 실행 환경 정보 (exe로 배포됐는지, 개발 중인지 등)
import os              # 파일/폴더 경로 다루기

import requests as rq  # 인터넷 주소로 웹페이지 내용을 가져오는 도구 (rq라는 별명으로 사용)

# Selenium: 크롬 브라우저를 코드로 직접 조종하는 도구
from selenium.common import TimeoutException, NoSuchElementException, WebDriverException
                       # 오류 종류들: 시간초과 / 요소를 못 찾음 / 브라우저 연결 오류
from selenium.webdriver.common.by import By
                       # 웹페이지에서 버튼·입력창 등을 찾는 방법 (ID로, CSS로, 등)
from selenium.webdriver.support import expected_conditions as EC
                       # "버튼이 클릭 가능한 상태가 될 때까지 기다려" 같은 조건 모음
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.wait import WebDriverWait
                       # 지정한 조건이 될 때까지 최대 N초 기다리는 기능
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
                       # 크롬 드라이버 버전 자동 관리 (크롬 업데이트 시 자동 대응)

from bs4 import BeautifulSoup as BS
                       # HTML 페이지를 분석해서 원하는 정보만 꺼내는 도구
                       # 비유: 신문에서 원하는 기사만 가위로 오려내는 것

from datetime import datetime  # 날짜·시각을 다루는 도구
from PySide6.QtCore import QObject, Signal
                       # GUI(화면)와 소통하는 신호(Signal) 시스템
                       # 비유: 라디오 방송처럼 정보를 화면에 쏴주는 것
from PySide6.QtWidgets import QMessageBox  # 팝업 알림창
from multiprocessing import Process        # 별도 프로세스 실행 (현재 미사용)
import keyboard        # 키보드 입력 감지 (ESC 긴급중단용)
import pickle          # 파이썬 데이터를 파일에 저장하고 불러오는 도구
                       # 비유: 데이터를 냉동 보관했다가 나중에 해동해서 쓰는 것
import undetected_chromedriver as uc
                       # 봇(자동화) 탐지를 피하는 특수 크롬 드라이버
                       # 비유: 변장한 크롬 — 옥션 서버가 "이건 사람이 쓰는 브라우저구나"라고 착각하게 만듦
from datetime import datetime   # (위에서 이미 import 했지만 중복 선언)
from selenium_stealth import stealth
                       # 브라우저가 자동화 프로그램임을 숨기는 추가 스텔스 설정


# ============================================================
# Auction 클래스 — 자동입찰의 모든 기능을 담은 상자
# ============================================================
# QObject를 상속받아 Qt 신호(Signal) 기능을 사용할 수 있게 됩니다.
class Auction(QObject):

    # ── Qt 신호(Signal) 정의 ────────────────────────────────────────────────
    # 신호는 "라디오 채널"이라고 생각하세요.
    # 이 클래스가 화면(GUI)에 정보를 보낼 때 아래 채널들을 사용합니다.

    auction_operation_signal = Signal(str)
    # 채널 1: 동작 상태 메시지를 화면 로그창에 출력할 때 사용
    # 예) "로그인 중...", "입찰 완료!" 같은 문자열(str)을 전송

    auction_bid_results = Signal(list)
    # 채널 2: 입찰 결과 데이터(리스트)를 화면에 전달할 때 사용
    # 예) [입찰가격, 입찰시각, 네트워크지연시간, ...]

    auction_bid_title = Signal(str)
    # 채널 3: 상품 이름을 화면 상단에 표시할 때 사용

    login_needed_signal = Signal()
    # 채널 4: "사용자가 직접 로그인해야 합니다" 알림 → GUI의 [로그인 완료] 버튼 활성화

    # ── 초기화 함수 ─────────────────────────────────────────────────────────
    def __init__(self):
        """
        Auction 객체가 처음 만들어질 때 딱 한 번 실행되는 함수.
        필요한 변수들을 미리 준비합니다.
        비유: 경매 도우미 로봇을 처음 켰을 때 초기 세팅하는 과정
        """
        super().__init__()

        self.local_data = threading.local()
        # 스레드별 전용 저장소 — 여러 입찰이 동시에 실행될 때
        # 각 스레드가 서로의 데이터를 덮어쓰지 않도록 분리된 공간
        # 비유: 요리사마다 자기 도마가 따로 있는 것

        self._login_event = threading.Event()
        # 로그인 완료를 기다리는 신호기
        # 비유: 신호등처럼, 로그인이 끝나면 초록불(set)이 켜져서 다음 단계로 진행


    # ============================================================
    # _data_path() — 파일 경로를 올바르게 만들어주는 도우미 함수
    # ============================================================
    @staticmethod
    def _data_path(filename):
        """
        개발할 때와 exe로 배포했을 때, 파일이 있는 위치가 달라집니다.
        이 함수는 어느 환경에서든 올바른 파일 경로를 돌려줍니다.

        예) filename = "auction_cookies.pkl" 이라고 하면
            개발 중:  C:/Aucton/auction_cookies.pkl
            exe 실행: C:/바탕화면/AuctionApp/auction_cookies.pkl  (exe 옆 폴더)
        """
        if getattr(sys, 'frozen', False):
            # PyInstaller로 만든 exe 파일로 실행 중인 경우
            # exe 파일이 있는 폴더를 기준으로 경로를 만듦
            base = os.path.dirname(sys.executable)
        else:
            # 일반 파이썬 개발 환경에서 실행 중인 경우
            # 현재 작업 폴더(프로젝트 루트)를 기준으로 경로를 만듦
            base = os.getcwd()
        return os.path.join(base, filename)


    # ============================================================
    # trigger_manual_login() — "[로그인 완료] 버튼" 클릭 시 호출
    # ============================================================
    def trigger_manual_login(self):
        """
        GUI에서 사용자가 [로그인 완료] 버튼을 누르면 이 함수가 실행됩니다.
        loginstart() 함수가 사용자 로그인을 기다리고 있는데,
        이 함수를 호출하면 "로그인 됐어!" 신호를 보내서 대기를 해제합니다.

        비유: 선생님이 출석 확인을 기다리는데, 학생이 손을 들어서 "저 왔어요!" 하는 것
        """
        self._login_event.set()
        # _login_event 신호기를 초록불로 바꿔서 loginstart()의 대기를 해제


    # ============================================================
    # check_session_cookies() — 저장된 로그인 쿠키를 불러와서 세션 만들기
    # ============================================================
    def check_session_cookies(self):
        """
        지난번에 저장해둔 로그인 쿠키(auction_cookies.pkl)를 읽어서
        새 인터넷 세션에 적용합니다.

        쿠키(Cookie)란?
          웹사이트가 "이 사람 아까 로그인했음"을 기억하는 작은 데이터 조각.
          비유: 도서관 출입증 — 한 번 신분 확인하면 도장을 찍어줘서,
                다시 올 때 그 도장만 보여주면 바로 들어갈 수 있는 것

        반환값:
          성공: 쿠키가 적용된 requests.Session 객체 (인터넷 요청에 사용)
          실패: None (쿠키 파일이 없거나 읽기 오류)
        """
        try:
            # 저장된 쿠키 파일을 열어서 데이터를 불러옴 (pickle = 냉동 데이터 해동)
            with open(self._data_path("auction_cookies.pkl"), "rb") as f:
                cookies = pickle.load(f)

            # 새로운 인터넷 세션(연결) 생성
            session = rq.Session()

            # 불러온 쿠키 하나하나를 세션에 붙여넣기
            for cookie in cookies:
                session.cookies.set(
                    name=cookie['name'],       # 쿠키 이름 (예: "AGP")
                    value=cookie['value'],     # 쿠키 값 (긴 문자열)
                    domain=cookie.get('domain', '.auction.co.kr')
                    # 쿠키가 적용될 도메인 — 없으면 옥션 기본값 사용
                )

            return session   # 쿠키가 담긴 세션 반환

        except Exception as e:
            # 쿠키 파일이 없거나, 읽는 도중 문제가 생기면 None 반환
            print(f"세션 쿠키 확인 중 오류: {e}")
            return None


    # ============================================================
    # process_task() — 고정가 모드에서 스레드 하나당 실행되는 작업
    # ============================================================
    def process_task(self, closing_time, interrupted, finished):
        """
        고정가 모드(fixedMultipleBid)에서 각 입찰 스레드가 실행하는 함수.
        브라우저 하나를 열고 → 로그인 → 상품 정보 수집 → 입찰 대기를 순서대로 진행합니다.

        매개변수:
          closing_time : 이 스레드가 담당하는 마감 시각 (예: "14:30:00.500")
          interrupted  : 중단 여부를 확인하는 함수 (ESC 키 누르면 True 반환)
          finished     : 작업 완료 신호 (GUI에 "끝났어요" 알림)
        """
        # 현재 스레드의 고유 번호 (신분증 같은 것)
        thread_id = threading.get_ident()

        # 스레드 전용 저장소가 없으면 새로 만들기
        if not hasattr(self.local_data, "thread_data"):
            self.local_data.thread_data = {}

        # 이 스레드만의 데이터 공간에 마감시간, 중단함수, 완료신호 저장
        self.local_data.thread_data[thread_id] = {
            'closing_time': closing_time,
            'interrupted': interrupted,
            'finished': finished
        }

        # 이 스레드 전용 크롬 브라우저 열기 (각 스레드가 자기 브라우저를 가짐)
        self.local_data.thread_data[thread_id]['browser'] = self.setupbrowser()

        # 로그인이 성공하면 상품 크롤링(정보 수집) 시작
        if self.loginstart(finished):
            self.startCrawling(interrupted)


    # ============================================================
    # fixedMultipleBid() — 고정가 모드: 여러 가격을 동시에 입찰
    # ============================================================
    def fixedMultipleBid(self, closing_time, interrupted, finished):
        """
        고정가 모드에서 여러 입찰을 동시에 진행합니다.
        각 입찰가마다 별도 스레드(독립 작업자)를 만들어서 동시에 실행합니다.

        예) 고정가가 3개 [5만원, 6만원, 7만원]이면
            스레드 3개가 각각 브라우저를 열고 동시에 입찰 대기

        봇 탐지 방지를 위해 스레드 시작 사이에 20초 간격을 둡니다.
        (여러 브라우저가 동시에 갑자기 열리면 의심받을 수 있음)
        """
        taskCount = len(closing_time)   # 입찰 건수 (= 마감시간 개수)

        # 각 스레드에 넘길 인자 목록 만들기
        # 예) [(마감시간1, interrupted, finished), (마감시간2, ...), ...]
        params_list = [(closing_time[i], interrupted, finished) for i in range(taskCount)]

        threads = []   # 생성된 스레드들을 담아두는 목록

        for params in params_list:
            # 스레드 생성: process_task 함수를 이 스레드가 실행하도록 설정
            thread = threading.Thread(target=self.process_task, args=params)
            threads.append(thread)
            thread.start()          # 스레드 시작 (비동기 실행)
            time.sleep(20)          # 봇 탐지 방지: 다음 스레드 시작 전 20초 대기

        # 모든 스레드가 끝날 때까지 기다리기
        for thread in threads:
            thread.join()           # 이 스레드가 완전히 끝날 때까지 대기

        # 모든 입찰 스레드가 끝나면 GUI에 "작업 완료" 신호 전송
        if finished:
            finished.emit(False)


    # ============================================================
    # auctionStart() — 입찰 시작의 관문: 모드를 판단하고 분기
    # ============================================================
    def auctionStart(self, startData, closing_time, interrupted, finished=None):
        """
        GUI에서 [입찰시작] 버튼을 누르면 최종적으로 이 함수가 실행됩니다.
        startData의 길이를 보고 일반 모드인지 고정가 모드인지 판단합니다.

        startData 구조:
          일반 모드 (길이 > 4): [URL, 최고가, 추가금액, 아이디, 비밀번호]
          고정가 모드 (길이 ≤ 4): [URL, [고정가격들], 아이디, 비밀번호]

        매개변수:
          startData    : GUI에서 입력한 데이터 목록
          closing_time : 마감 시각 목록
          interrupted  : 중단 여부 확인 함수
          finished     : 완료 신호
        """
        self.fixedplug = False   # 기본값: 일반 모드 (고정가 모드가 아님)
        self.url = startData[0]  # 입찰할 상품 URL 저장

        if len(startData) > 4:
            # ── 일반 모드 ──────────────────────────────────────────────
            # 현재가 + 추가금액으로 입찰, 최고가 한도 적용

            self.maxPrice = int(startData[1])
            # 최고 입찰 한도 (이 금액을 넘으면 입찰 포기)

            if startData[2].isdigit():
                self.AdditionalAmount = int(startData[2])
                # 현재가에 더할 추가 금액 (예: 현재가 50,000 + 추가 1,000 = 51,000원 입찰)
            else:
                self.AdditionalAmount = 0   # 추가금액 입력이 없으면 0으로 처리

            self.auctionID = startData[3]   # 옥션 로그인 아이디
            self.auctionPW = startData[4]   # 옥션 로그인 비밀번호

            self.closing_time = closing_time[0]   # 마감 시각 (예: "14:30:00.500")

            # 크롬 브라우저 열기 → 로그인 → 상품 정보 수집 순서로 진행
            self.setupbrowser()
            if self.loginstart(finished):
                self.startCrawling(interrupted, finished)

        else:
            # ── 고정가 모드 ────────────────────────────────────────────
            # 미리 정해둔 가격으로 각각 입찰 (최대 4개)

            self.fixedplug = True    # 고정가 모드 플래그 ON
            self.maxPrice = 0        # 고정가 모드에서는 최고가 한도 사용 안 함
            self.AdditionalAmount = 0

            # "0"이 아닌 가격만 골라서 정수 리스트로 만들기
            # 예) ["50000", "60000", "0", "0"] → [50000, 60000]
            self.fixedPricelst = [int(item) for item in startData[1] if item != "0"]

            self.auctionID = startData[2]   # 옥션 아이디
            self.auctionPW = startData[3]   # 옥션 비밀번호

            # 유효한 가격 개수만큼만 마감시간도 잘라서 사용
            closing_timelst = [item for _, item in zip(self.fixedPricelst, closing_time)]

            # 여러 스레드로 동시 입찰 시작
            self.fixedMultipleBid(closing_timelst, interrupted, finished)


    # ============================================================
    # message_view() — 팝업 알림창 띄우기
    # ============================================================
    def message_view(self, msg):
        """
        화면에 팝업 알림창을 띄웁니다.
        비유: 스마트폰 알림처럼 화면 위에 메시지 박스가 나타나는 것

        매개변수:
          msg : 팝업에 표시할 메시지 문자열
        """
        msgstr = QMessageBox()
        msgstr.setWindowTitle("알림")   # 팝업 창 제목
        msgstr.setText(msg)             # 팝업 내용
        msgstr.exec()                   # 팝업 표시 (사용자가 확인 누를 때까지 대기)


    # ============================================================
    # setupbrowser() — 크롬 브라우저를 열고 봇 탐지 우회 설정
    # ============================================================
    def setupbrowser(self):
        """
        옥션 자동화에 사용할 크롬 브라우저를 열고 설정합니다.
        단순히 브라우저를 여는 게 아니라, 옥션 서버가
        "이건 사람이 쓰는 브라우저야"라고 착각하도록 여러 위장 설정을 합니다.

        반환값:
          성공: 설정된 browser 객체
          실패: False
        """
        options = uc.ChromeOptions()   # 크롬 실행 옵션 설정 객체 생성

        # ── 봇 탐지 우회 설정들 ──────────────────────────────────────────
        # (주석 처리된 --headless=new: 창 없이 백그라운드 실행 — 현재 비활성화)
        # options.add_argument('--headless=new')

        options.add_argument('--no-sandbox')
        # 샌드박스(보안 격리) 비활성화 — 일부 환경에서 크롬이 안 열릴 때 필요

        options.add_argument('--window-size=1024,768')
        # 브라우저 창 크기를 1024x768로 설정 (너무 작거나 크면 의심받을 수 있음)

        options.add_argument('--disable-blink-features=AutomationControlled')
        # "이 브라우저는 자동화 프로그램에 의해 제어되고 있습니다" 표시 제거

        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        # 사이트 격리 기능 비활성화 (여러 창 간 통신에 필요)

        options.add_argument('--disable-extensions')    # 확장 프로그램 비활성화
        options.add_argument('--disable-automation')    # 자동화 모드 표시 제거
        options.add_argument('--disable-dev-shm-usage') # 공유 메모리 문제 방지
        options.add_argument('--disable-web-security')  # 웹 보안 정책 완화
        options.add_argument('--allow-running-insecure-content')  # 혼합 콘텐츠 허용

        options.add_argument(
            f'--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            f'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        # User-Agent 설정: 서버에게 "나는 일반 사용자 크롬 브라우저야"라고 속이는 신분증
        # 비유: 경비원에게 신분증을 보여줄 때, 로봇이 아닌 사람 신분증을 보여주는 것

        try:
            # ── undetected-chromedriver로 크롬 실행 ──────────────────────
            # 일반 selenium이 아닌 uc(undetected-chromedriver)를 사용
            # → 봇 탐지 시스템을 더 효과적으로 우회
            self.browser = uc.Chrome(
                options=options,
                use_subprocess=True    # 별도 프로세스로 실행 (안정성 향상)
            )

            # ── CDP 명령어로 자동화 흔적 제거 ────────────────────────────
            # CDP(Chrome DevTools Protocol): 브라우저 내부를 직접 제어하는 방법
            # 아래 코드는 크롬 드라이버가 남기는 특정 변수명들을 페이지 로드 시마다 삭제
            # (옥션 서버가 이 변수를 보고 봇인지 판단하기 때문)
            self.browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                '''
            })
            # 비유: 집에 손님이 오기 전에 "청소 도우미가 왔다 갔음" 흔적을 지우는 것

            # 창 크기 재적용 (옵션 설정 후 한 번 더 확실히 고정)
            self.browser.set_window_size(1024, 768)
            time.sleep(1)   # 창 크기 변경이 적용될 때까지 1초 대기

            # 페이지 로딩 관련 타임아웃 설정
            self.browser.set_page_load_timeout(30)
            # 페이지가 30초 안에 안 열리면 오류 처리

            self.browser.implicitly_wait(10)
            # 요소(버튼, 입력창 등)를 찾을 때 최대 10초까지 기다리기
            # (페이지가 느리게 로딩되더라도 조급하게 포기하지 않음)

            return self.browser   # 설정 완료된 브라우저 반환

        except Exception as e:
            # 브라우저 실행 실패 시 오류 메시지를 화면에 전송
            self.auction_operation_signal.emit(f"브라우저 설정 실패: {str(e)}")
            return False


    # ============================================================
    # validate_cookies() — 필수 쿠키가 모두 있는지 검사
    # ============================================================
    def validate_cookies(self, cookies):
        """
        로그인에 반드시 필요한 쿠키 3가지가 모두 있는지 확인합니다.

        필수 쿠키:
          'auction' : 기본 인증 쿠키
          'AGP'     : 옥션 사용자 세션 쿠키
          'bcp'     : 보안 관련 쿠키

        반환값:
          True  → 3가지 모두 있음 (로그인 상태 유효)
          False → 하나라도 없음 (재로그인 필요)
        """
        # 필수 쿠키 목록을 딕셔너리로 준비 (처음엔 모두 None = "아직 못 찾음")
        required_cookies = {
            'auction': None,
            'AGP': None,
            'bcp': None
        }

        # 받아온 쿠키 목록에서 필수 쿠키를 찾아서 값 채우기
        for cookie in cookies:
            if cookie['name'] in required_cookies:
                required_cookies[cookie['name']] = cookie['value']

        # 모든 값이 None이 아닌지(= 모두 찾았는지) 확인해서 True/False 반환
        return all(required_cookies.values())


    # ============================================================
    # check_cookie_expiry() — 쿠키 만료 여부 확인
    # ============================================================
    def check_cookie_expiry(self, cookies):
        """
        저장된 쿠키들이 아직 유효한지(만료되지 않았는지) 확인합니다.

        쿠키에는 유효기간이 있습니다.
        비유: 우유 유통기한처럼 — 기한이 지나면 사용 불가

        반환값:
          True  → 모든 쿠키가 아직 유효함
          False → 하나라도 만료된 쿠키가 있음
        """
        now = datetime.now()   # 현재 시각

        # 각 쿠키의 만료시간(expiry)이 현재 시각보다 나중인지 확인
        # expiry가 없는 쿠키는 만료되지 않은 것으로 간주 (now를 기본값으로 사용)
        return all(cookie.get('expiry', now) > now for cookie in cookies)


    # ============================================================
    # save_cookies() — 로그인 쿠키를 파일에 저장
    # ============================================================
    def save_cookies(self, cookies, filename):
        """
        현재 브라우저의 로그인 쿠키를 파일에 저장합니다.
        다음에 프로그램을 실행할 때 이 쿠키로 자동 로그인을 시도합니다.

        비유: 도서관 출입증을 지갑에 넣어두는 것 — 다음에 올 때 꺼내서 바로 사용

        매개변수:
          cookies  : 저장할 쿠키 목록
          filename : 저장할 파일 이름 (예: "auction_cookies.pkl")

        반환값:
          True  → 저장 성공
          False → 저장 실패
        """
        try:
            if not cookies:
                # 쿠키가 비어있으면 저장할 게 없음
                self.auction_operation_signal.emit("쿠키가 비어있습니다")
                return False

            # 파일 경로 생성 후 pickle로 저장 (냉동 보관)
            filepath = self._data_path(filename)
            with open(filepath, "wb") as f:
                pickle.dump(cookies, f)

            # 저장한 쿠키를 현재 브라우저에도 바로 적용
            for cookie in cookies:
                try:
                    if 'expiry' in cookie:
                        cookie['expiry'] = int(cookie['expiry'])
                        # 만료시간을 정수형으로 변환 (브라우저가 요구하는 형식)
                    self.browser.add_cookie(cookie)   # 브라우저에 쿠키 추가
                except Exception as e:
                    self.auction_operation_signal.emit(f"쿠키 적용 실패: {cookie['name']}")
                    continue   # 한 쿠키 실패해도 나머지 계속 진행

            return True

        except Exception as e:
            self.auction_operation_signal.emit(f"쿠키 저장 실패: {e}")
            return False


    # ============================================================
    # loginProcess() — 자동 로그인 시도 (현재 봇 탐지로 차단됨)
    # ============================================================
    def loginProcess(self, browser):
        """
        코드로 자동으로 아이디/비밀번호를 입력하고 로그인을 시도합니다.
        현재 옥션의 봇 탐지 시스템에 의해 차단되어 실제로는 사용되지 않습니다.
        (참고용 코드로 남겨둠)

        사람처럼 보이기 위해:
          - 랜덤한 시간 간격으로 대기
          - 마우스를 버튼 위로 이동 후 클릭
          - 아이디/비밀번호를 한 글자씩 천천히 입력
        """
        import random   # 랜덤 숫자 생성 (자연스러운 딜레이에 사용)

        try:
            # 최대 20초까지 기다리는 대기 객체 생성
            wait = WebDriverWait(browser, 20)

            # 페이지 로드 후 사람처럼 2~4초 랜덤 대기
            time.sleep(random.uniform(2, 4))

            # 로그인 버튼 찾아서 클릭
            login_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.usermenu ul li:first-child a"))
            )
            # element_to_be_clickable: 버튼이 화면에 나타나고 클릭 가능한 상태가 될 때까지 대기

            # 마우스를 버튼 위로 이동한 후 클릭 (사람처럼 행동)
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(browser)
            actions.move_to_element(login_button).pause(random.uniform(0.5, 1.5)).click().perform()
            time.sleep(random.uniform(2, 4))

            # 아이디 입력창 찾기
            username = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id='typeMemberInputId']"))
            )
            actions.move_to_element(username).click().perform()
            time.sleep(random.uniform(0.5, 1.0))

            # 아이디를 한 글자씩 입력 (사람이 타이핑하는 것처럼 보이게)
            for char in self.auctionID:
                username.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))   # 글자 사이 50~150ms 랜덤 대기

            time.sleep(random.uniform(0.5, 1.0))

            # 비밀번호 입력창 찾기
            password = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id='typeMemberInputPassword']"))
            )
            actions.move_to_element(password).click().perform()
            time.sleep(random.uniform(0.5, 1.0))

            # 비밀번호도 한 글자씩 입력
            for char in self.auctionPW:
                password.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))

            time.sleep(random.uniform(1, 2))

            # 로그인 제출 버튼 클릭
            login_submit = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[id='btnLogin']"))
            )
            actions.move_to_element(login_submit).pause(random.uniform(0.5, 1.0)).click().perform()
            time.sleep(random.uniform(3, 5))   # 로그인 처리 완료까지 3~5초 대기

            # 로그인 성공 여부 확인 후 결과 반환
            return self.verify_login(browser)

        except Exception as e:
            self.auction_operation_signal.emit(f"로그인 프로세스 중 오류 발생: {str(e)}")
            return False


    # ============================================================
    # verify_login() — 현재 로그인 상태인지 확인
    # ============================================================
    def verify_login(self, browser):
        """
        브라우저가 현재 로그인된 상태인지 확인합니다.
        로그인됐다면 페이지에 "로그아웃" 링크가 보이므로, 그것을 찾아서 판단합니다.

        비유: 도서관에 들어왔을 때 "회원 전용 열람실 이용 중" 표시가 있으면
              로그인된 것으로 간주하는 것

        반환값:
          True  → 로그인 상태 확인됨
          False → 로그인 상태 아님 (또는 확인 불가)
        """
        try:
            # 페이지에서 "logout"이 포함된 링크를 찾기 (최대 5초 대기)
            logout_link = WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='logout']"))
            )

            if logout_link and "로그아웃" in logout_link.text:
                # "로그아웃" 텍스트가 있는 링크를 찾았다 = 현재 로그인 상태
                self.auction_operation_signal.emit("로그인 상태 확인 완료")
                return True

            return False   # 링크는 있지만 텍스트가 다름

        except (TimeoutException, NoSuchElementException):
            # 5초 안에 로그아웃 링크를 못 찾음 = 로그인 상태 아님
            self.auction_operation_signal.emit("로그인 상태가 아닙니다")
            return False
        except Exception as e:
            self.auction_operation_signal.emit(f"로그인 상태 확인 중 오류: {str(e)}")
            return False


    # ============================================================
    # loginstart() — 로그인 전체 흐름 관리 (핵심 로그인 함수)
    # ============================================================
    def loginstart(self, finished=None):
        """
        로그인 과정을 단계별로 진행합니다.

        [1단계] 옥션 메인 페이지 접속
        [2단계] 기존 쿠키 세션으로 이미 로그인된 상태인지 확인
        [3단계] 로그인 안 돼 있으면 → 사용자에게 직접 로그인 요청

        현재 자동 로그인이 봇 탐지에 막혀있어서,
        사용자가 직접 브라우저에서 로그인한 후 [로그인 완료] 버튼을 누르거나
        로그인 상태가 자동으로 감지될 때까지 최대 5분 대기합니다.

        반환값:
          True  → 로그인 성공 (다음 단계인 입찰 진행 가능)
          False → 로그인 실패 또는 시간 초과
        """
        # ── 브라우저 인스턴스 선택 ───────────────────────────────────────────
        # 고정가 모드(스레드 여러 개)인 경우, 이 스레드 전용 브라우저를 사용
        # 일반 모드인 경우, 공통 브라우저(self.browser)를 사용
        if hasattr(self.local_data, "thread_data"):
            thread_id = threading.get_ident()
            browser = self.local_data.thread_data[thread_id]["browser"]
            self.closing_time = self.local_data.thread_data[thread_id]["closing_time"]
        else:
            browser = self.browser

        # 브라우저가 제대로 열리지 않은 경우 바로 실패 처리
        if browser is None:
            self.auction_operation_signal.emit("브라우저 초기화에 실패했습니다.")
            if finished:
                finished.emit(False)
            return False

        try:
            # ── [1단계] 옥션 메인 페이지 접속 ──────────────────────────────
            self.auction_operation_signal.emit("옥션 메인 페이지 접속 중...")
            browser.get("http://www.auction.co.kr/")
            # Cloudflare 같은 보안 검증 페이지가 뜰 수 있어서 최대 30초 대기
            wait_interval = 2   # 2초마다 확인
            for elapsed in range(0, 30, wait_interval):
                try:
                    if browser.find_elements(By.CSS_SELECTOR, "div.usermenu"):
                        # 메뉴 영역이 보이면 페이지 정상 로딩 완료
                        self.auction_operation_signal.emit("페이지 로딩 완료")
                        break
                    if "사용자 활동 검토" in browser.page_source:
                        # Cloudflare 봇 검증 페이지 — 사용자가 직접 풀어야 함
                        self.auction_operation_signal.emit(
                            f"보안 검증 진행 중... ({elapsed}/{30}초) — 브라우저에서 직접 해결해 주세요."
                        )
                except Exception:
                    pass
                time.sleep(wait_interval)

            time.sleep(1)   # 페이지 완전 안정화 대기

            # ── [2단계] 기존 세션(쿠키)으로 로그인 여부 확인 ─────────────
            self.auction_operation_signal.emit("기존 세션 확인 중...")
            if self.verify_login(browser):
                # 이미 로그인된 상태면 바로 다음 단계로!
                self.auction_operation_signal.emit("기존 세션으로 로그인 상태 확인 완료!")
                return True

            # ── [3단계] 수동 로그인 대기 ────────────────────────────────────
            # 자동 로그인이 막혀있으니 사용자에게 직접 로그인 요청
            self._login_event.clear()   # 로그인 신호기를 빨간불로 초기화

            self.auction_operation_signal.emit("━" * 30)
            self.auction_operation_signal.emit("  브라우저에서 직접 로그인해 주세요.")
            self.auction_operation_signal.emit("  로그인 후 자동 감지되거나,")
            self.auction_operation_signal.emit("  [로그인 완료] 버튼을 눌러주세요.")
            self.auction_operation_signal.emit("━" * 30)
            self.login_needed_signal.emit()   # GUI의 [로그인 완료] 버튼 활성화

            # 백그라운드에서 2초마다 로그인 상태를 자동으로 감지하는 함수
            def _poll_login(b):
                """
                사용자가 [로그인 완료] 버튼을 누르지 않더라도,
                브라우저에서 로그인이 완료되면 자동으로 감지합니다.
                2초마다 로그인 상태를 확인하는 "감시자" 역할
                """
                while not self._login_event.is_set():
                    time.sleep(2)   # 2초 대기 후 확인
                    try:
                        if self.verify_login(b):
                            self.auction_operation_signal.emit("로그인 자동 감지 완료!")
                            self._login_event.set()   # 신호기 초록불 → 대기 해제
                            break
                    except Exception:
                        pass   # 브라우저가 닫히는 등 예외 발생 시 조용히 무시

            # 감시 스레드를 백그라운드에서 시작 (daemon=True: 메인 종료 시 함께 종료)
            threading.Thread(target=_poll_login, args=(browser,), daemon=True).start()

            # 최대 5분(300초) 대기 — [로그인 완료] 버튼 클릭 또는 자동 감지 시 즉시 해제
            if self._login_event.wait(timeout=300):
                self.auction_operation_signal.emit("로그인 확인 완료! 입찰 준비를 시작합니다...")
                time.sleep(1)   # 로그인 후 페이지 안정화 대기
                return True

            # 5분이 지나도 로그인 안 됨 → 타임아웃 처리
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


    # ============================================================
    # bidWindow() — 입찰 창 열기
    # ============================================================
    def bidWindow(self, browser):
        """
        상품 페이지에서 [입찰하기] 버튼을 클릭해서 입찰 팝업 창을 엽니다.
        새 창이 열리면 그 창으로 포커스를 이동합니다.

        비유: 경매장에서 "이 물건에 입찰하겠습니다" 창구로 이동하는 것

        반환값:
          성공: 창 핸들 목록 [원래창, 입찰창] — 나중에 창 전환에 사용
          실패: False
        """
        try:
            # [입찰하기] 버튼이 클릭 가능한 상태가 될 때까지 최대 10초 대기
            bid_button = WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.ID, "ucControls_btn1"))
            )

            # 버튼 클릭 — 입찰 팝업 창이 열림
            bid_button.click()

            # 새 창이 열릴 때까지 최대 10초 대기
            WebDriverWait(browser, 10).until(lambda x: len(x.window_handles) > 1)

            handlers = browser.window_handles
            # handlers[0] = 원래 상품 페이지 창
            # handlers[1] = 새로 열린 입찰 창

            # 입찰 창으로 포커스 이동
            browser.switch_to.window(handlers[1])

            return handlers   # 창 핸들 목록 반환 (나중에 원래 창으로 돌아올 때 필요)

        except Exception as e:
            self.auction_operation_signal.emit(f"입찰창 열기 실패: {str(e)}")
            return False


    # ============================================================
    # fixedbid() — 고정가 모드: 입찰 버튼 클릭
    # ============================================================
    def fixedbid(self, browser):
        """
        고정가 모드에서 입찰 금액을 미리 입력해둔 상태에서
        [입찰] 버튼만 클릭합니다.
        JavaScript로 클릭하는 이유: 일반 .click()보다 안정적으로 동작하기 때문

        비유: 이미 가격표를 들고 있고, 정확한 시각에 손만 번쩍 드는 것
        """
        # CSS 선택자로 입찰 버튼 요소 찾기
        button = browser.find_element(By.CSS_SELECTOR, "input#buttonBid")

        # JavaScript로 클릭 실행 (더 확실하게 클릭됨)
        browser.execute_script("arguments[0].click();", button)


    # ============================================================
    # refresh() — 입찰 창 새로고침 및 가격 업데이트
    # ============================================================
    def refresh(self, browser, last=False):
        """
        입찰 창을 새로고침해서 최신 가격을 가져옵니다.
        last=True일 때는 최신 가격으로 실제 입찰까지 제출합니다.

        매개변수:
          browser : 제어할 브라우저
          last    : True면 입찰 최종 제출, False면 가격 확인만

        흐름:
          1. 페이지 새로고침 → 최신 현재가 읽기
          2. 최신현재가 + 추가금액 = 실제 입찰가 계산
          3. 최고가 한도 이하인 경우만 입찰 진행
          4. last=True면 JavaScript로 입찰 폼 제출
        """
        browser.refresh()   # 페이지 새로고침 (최신 가격 로딩)

        if self.refreshError:
            # refreshError=True일 때만 가격 처리 진행
            # (오류 발생 후에는 False로 바뀌어서 이 블록을 건너뜀)
            try:
                # 추가금액이 있으면 다른 CSS 선택자로 현재가를 찾음
                price_selector = (
                    "tbody > tr:nth-of-type(1) > td:nth-of-type(1) > .price"
                    if self.AdditionalAmount > 0
                    else 'b.name span.price'
                )

                # 현재가 텍스트 읽기 (예: "52,000원")
                price_element_text = browser.find_element(By.CSS_SELECTOR, price_selector).text

                # 숫자만 추출 → 정수로 변환 (쉼표, "원" 제거)
                price_data = int(price_element_text.replace(',', '').replace('원', ''))

                # 실제 입찰가 = 현재가 + 추가금액
                price = price_data + self.AdditionalAmount

                if price <= self.maxPrice:
                    # 최고 한도 이하인 경우에만 입찰 진행
                    if last:
                        # ── 실제 입찰 제출 ────────────────────────────────
                        # ASP.NET 폼 제출에 필요한 숨겨진 필드값 가져오기
                        viewstate_value = browser.find_element(
                            By.ID, "__VIEWSTATE"
                        ).get_attribute('value')
                        # __VIEWSTATE: ASP.NET 페이지 상태값 (서버에서 폼 유효성 검증에 사용)

                        eventtarget_value = "buttonBid"    # 클릭한 버튼 ID
                        eventargument_value = ""           # 추가 인수 (없음)

                        # JavaScript로 입찰 폼을 채우고 서버에 제출
                        combined_script = f"""
                        document.querySelector('#ctrlPrice').value = '{price}';
                        document.querySelector('#__VIEWSTATE').value = '{viewstate_value}';
                        document.querySelector('#__EVENTTARGET').value = '{eventtarget_value}';
                        document.querySelector('#__EVENTARGUMENT').value = '{eventargument_value}';
                        __doPostBack('{eventtarget_value}', '{eventargument_value}');
                        """
                        # __doPostBack: ASP.NET 페이지에서 서버로 데이터를 전송하는 함수
                        browser.execute_script(combined_script)
                    else:
                        # last=False일 때는 가격 입력창을 비워두기만 함 (다음 입력 준비)
                        input_element = WebDriverWait(browser, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "#ctrlPrice"))
                        )
                        input_element.clear()
                else:
                    # 입찰가가 최고 한도를 초과한 경우
                    if not self.fixedplug:
                        self.over_limit = True   # 한도 초과 플래그 ON → 입찰 포기

            except Exception as e:
                # 새로고침 후 요소를 찾지 못하거나 오류 발생 시
                self.refreshError = False   # 이후 refresh() 호출 시 처리 건너뜀
                self.auction_operation_signal.emit(
                    f"입찰 새로고침 에러가 발생했습니다. \n"
                    f" 안전하게 'ALL Chrome Kill' 버튼을 클릭하여 모든 브라우저를 종료한 후 \n"
                    f" '입찰시작' 버튼을 클릭해 주세요."
                )
                try:
                    # 혹시 "이미 낙찰 범위에" 오류 메시지가 화면에 있는지 확인
                    error_element = browser.find_element(By.CSS_SELECTOR, "#ErrorMsg")
                    error_message = error_element.text
                    if "이미 낙찰 범위에" in error_message:
                        self.auction_operation_signal.emit(
                            "이미 낙찰 범위에 계시기 때문에 입찰하실 수 없습니다."
                        )
                        # 안내 팝업의 닫기 버튼 클릭
                        close_button = browser.find_element(By.CSS_SELECTOR, "#bottombutton img")
                        browser.execute_script("arguments[0].click();", close_button)
                except:
                    pass   # 오류 메시지 요소가 없으면 무시


    # ============================================================
    # bidding() — 입찰 후 결과 확인창 닫기
    # ============================================================
    def bidding(self, browser):
        """
        입찰 버튼을 누른 후 나타나는 확인 팝업이나 결과창을 닫습니다.

        흐름:
          1. JavaScript alert 팝업이 있으면 확인 클릭
          2. 하단 닫기 버튼 클릭으로 입찰 완료 처리

        비유: 경매장에서 손을 들고 나서, 직원이 확인을 받으러 오면
              "네, 맞습니다" 라고 답하고 영수증을 받는 것
        """
        try:
            alert = browser.switch_to.alert   # JavaScript alert 팝업 접근 시도
            alert.accept()                    # 팝업의 [확인] 버튼 클릭
        except:
            pass   # alert 팝업이 없으면 그냥 넘어감

        # 입찰 결과 창의 [닫기] 버튼 클릭
        close_button = browser.find_element(By.CSS_SELECTOR, "#bottombutton img")
        browser.execute_script("arguments[0].click();", close_button)
        # JavaScript로 클릭하는 이유: 일반 .click()보다 신뢰성이 높음


    # ============================================================
    # biddingPrice() — 현재 입찰 가격 추출
    # ============================================================
    def biddingPrice(self, soup):
        """
        BeautifulSoup으로 파싱한 상품 페이지에서 현재 입찰 가격을 읽어옵니다.

        매개변수:
          soup : BeautifulSoup으로 파싱된 HTML 객체

        반환값:
          현재 입찰 가격 (정수)  예) 52000
        """
        # CSS 선택자로 현재가 요소를 찾아 텍스트 추출
        start_price = soup.select_one(".redprice .present_price .present_num").text.replace(',', '')
        # 쉼표 제거 후 정수로 변환 (예: "52,000" → 52000)
        return int(start_price)


    # ============================================================
    # competition_ID_check() — 현재 최고 입찰자 정보 확인
    # ============================================================
    def competition_ID_check(self, browser):
        """
        입찰 후 현재 1위 입찰자의 아이디와 입찰 등록 시각을 확인합니다.
        내 아이디와 비교해서 낙찰 성공 여부를 판단하는 데 사용합니다.

        비유: 경매가 끝난 뒤 칠판의 1등 입찰자 이름을 확인하는 것

        반환값:
          (입찰자 아이디, 입찰 등록 시각) 튜플
          예) ("lanki", "2024-01-15 14:30:00.123")
        """
        # 입찰 기록 확인 링크 클릭 (checkEnd 함수를 호출하는 링크)
        auction_record_link = browser.find_element(By.CSS_SELECTOR, "a[href^='javascript:checkEnd']")
        browser.execute_script("arguments[0].click();", auction_record_link)

        # 입찰 목록 테이블에서 2번째 행(= 1위 입찰자)의 아이디 읽기
        bidder_id_element = browser.find_element(
            By.CSS_SELECTOR, ".bid_tbl2 tr:nth-child(2) td.bidid"
        )
        bidder_id_text = bidder_id_element.text
        # 예) "lanki***" (개인정보 보호를 위해 뒷부분이 ***로 표시됨)

        # 1위 입찰자의 입찰 등록 시각 읽기
        bidder_time_element = browser.find_element(
            By.CSS_SELECTOR, ".bid_tbl2 tr:nth-child(2) td:nth-child(2)"
        )
        bidder_time_text = bidder_time_element.text
        # 예) "2024-01-15 14:30:00.123"

        # "***" 부분 제거해서 순수 아이디만 추출 (예: "lanki***" → "lanki")
        bidder_id_clean = bidder_id_text.replace('***', '')

        browser.back()   # 이전 페이지로 돌아가기

        return bidder_id_clean, bidder_time_text


    # ============================================================
    # wait_for_event() — 마감 시각 문자열을 datetime 객체로 변환
    # ============================================================
    def wait_for_event(self, target_time_str):
        """
        GUI에서 입력된 마감 시각 문자열을 파이썬 datetime 객체로 변환합니다.
        datetime 객체로 변환해야 시간 비교가 가능합니다.

        매개변수:
          target_time_str : 마감 시각 문자열 (예: "26-01-15 14:30:00.500")
          형식: yy-mm-dd HH:MM:SS.mmm

        반환값:
          datetime 객체 (예: datetime(2026, 1, 15, 14, 30, 0, 500000))
        """
        target_time = datetime.strptime(target_time_str, '%y-%m-%d %H:%M:%S.%f')
        # strptime: 문자열을 datetime 객체로 파싱하는 함수
        # '%y-%m-%d %H:%M:%S.%f' = 연도2자리-월-일 시:분:초.밀리초
        return target_time


    # ============================================================
    # time_difference_calculation() — 네트워크 지연시간 계산
    # ============================================================
    def time_difference_calculation(self, new_target_time, now1):
        """
        내 PC에서 입찰 버튼을 누른 시각과
        옥션 서버에 실제로 등록된 시각의 차이(네트워크 지연)를 계산합니다.

        예) 내 PC 클릭 시각: 14:30:00.100
            서버 등록 시각:   14:30:00.250
            지연시간:         0.150초 (150밀리초)

        매개변수:
          new_target_time : 서버에 기록된 입찰 시각 문자열
          now1            : 내 PC에서 입찰한 시각 (datetime 객체)

        반환값:
          지연 시간 (초 단위 실수)  예) 0.15
        """
        time_difference = datetime.strptime(new_target_time, '%Y-%m-%d %H:%M:%S.%f')
        # '%Y-%m-%d ...' = 연도 4자리 형식 (서버 응답 형식)

        time_difference_result = abs((time_difference - now1).total_seconds())
        # abs(): 절대값 (음수가 되지 않도록)
        # total_seconds(): 시간 차이를 초 단위로 변환

        return time_difference_result


    # ============================================================
    # check_time() — 입찰 타이밍 정밀 제어 (핵심 중의 핵심!)
    # ============================================================
    def check_time(self, target_time, bidprice, handlers, interrupted, browser, interval=0.0001):
        """
        입찰 마감 시각까지 정밀하게 기다렸다가, 정확한 순간에 입찰 버튼을 누릅니다.
        이 프로그램의 가장 중요한 함수입니다.

        비유: 100미터 달리기 출발 총성 소리를 기다리는 것처럼,
              마감 시각이 되는 순간 즉시 버튼을 클릭합니다.

        [최적화 포인트]
        남은 시간에 따라 대기 간격을 다르게 합니다:
          - 2초 이상 남음  → 0.5초마다 확인 (CPU 절약)
          - 0.5~2초       → 50ms마다 확인
          - 100~500ms     → 5ms마다 확인
          - 100ms 미만    → 쉬지 않고 계속 확인 (최대 정밀도)

        매개변수:
          target_time : 입찰 마감 시각 (datetime 객체)
          bidprice    : 입찰가격
          handlers    : 브라우저 창 핸들 목록 [상품창, 입찰창]
          interrupted : 중단 여부 확인 함수 (ESC 키 누르면 True)
          browser     : 제어할 브라우저
          interval    : (미사용) 기존 방식의 대기 간격 (적응형으로 대체됨)
        """
        # ── Windows 타이머 해상도를 1ms로 향상 ──────────────────────────────
        # Windows의 기본 타이머 해상도는 15.6ms → time.sleep()이 최대 15.6ms 단위로만 작동
        # timeBeginPeriod(1)로 1ms 단위까지 정밀하게 만들어서 입찰 타이밍 정확도 향상
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
            _timer_period_set = True   # 나중에 원상복구 해야 함을 기억
        except Exception:
            _timer_period_set = False  # Windows 외 환경이거나 권한 없으면 그냥 진행

        # ── 입찰 창 준비: 새로고침 + 가격 입력창 비우기 ─────────────────────
        self.refresh(browser)   # 입찰 창 새로고침 (최신 상태로 갱신)
        try:
            input_element = WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#ctrlPrice"))
            )
            input_element.clear()   # 가격 입력창 비우기 (이전에 입력된 값 제거)
        except Exception as e:
            self.auction_operation_signal.emit("입찰금액 입력폼에 문제 발생..")
            if _timer_period_set:
                ctypes.windll.winmm.timeEndPeriod(1)   # 타이머 해상도 원상복구
            return

        # ── 적응형 대기 함수 ─────────────────────────────────────────────────
        def _adaptive_wait(target):
            """
            마감 시각까지 남은 시간에 따라 대기 간격을 자동으로 조절합니다.
            CPU를 아끼면서도 마감 순간에는 최대한 정밀하게 동작합니다.

            반환값:
              True  → 마감 시각 도달! 입찰 실행해도 됨
              False → 사용자가 중단 요청 (ESC 키 등)
            """
            while True:
                if interrupted():
                    return False   # 중단 신호가 오면 즉시 중단

                now = datetime.now()
                remaining = (target - now).total_seconds()
                # remaining: 마감까지 남은 시간 (초 단위, 음수면 이미 지남)

                if remaining <= 0:
                    return True   # 마감 시각 도달! 입찰 버튼 누를 시간
                elif remaining > 2.0:
                    time.sleep(0.5)    # 여유 있음: 0.5초 자고 다시 확인 (CPU 절약)
                elif remaining > 0.5:
                    time.sleep(0.05)   # 조금 남음: 50ms마다 확인
                elif remaining > 0.1:
                    time.sleep(0.005)  # 얼마 안 남음: 5ms마다 확인
                # 100ms 미만: sleep 없이 계속 반복 (바쁜 대기, 최대 정밀도)

        # ── 모드별 입찰 실행 ─────────────────────────────────────────────────
        if self.fixedplug:
            # ── 고정가 모드 ───────────────────────────────────────────────
            # 가격을 미리 입력해두고, 마감 시각에 버튼만 클릭
            self.auction_operation_signal.emit("고정 금액 입찰입니다..................")
            input_element.send_keys(bidprice)   # 입찰가 미리 입력 (마감 전에 준비 완료)

            fired = _adaptive_wait(target_time)   # 마감 시각까지 정밀 대기
            if not fired:
                # 사용자가 중단 요청한 경우
                self.auction_operation_signal.emit("작업이 중단되었습니다.")
                if _timer_period_set:
                    ctypes.windll.winmm.timeEndPeriod(1)
                return

            now = datetime.now()         # 실제 입찰 시각 기록 (결과 분석용)
            self.fixedbid(browser)       # 입찰 버튼 클릭! (버튼만 누르면 되므로 매우 빠름)
            end = datetime.now()         # 버튼 클릭 완료 시각 기록
            self.bidding(browser)        # 결과 확인창 닫기
        else:
            # ── 일반 모드 ─────────────────────────────────────────────────
            # 마감 시각에 페이지를 새로고침해서 최신 가격을 가져온 후 입찰 제출
            # (참고: 페이지 새로고침이 포함되어 고정가 모드보다 약간 느림)
            self.auction_operation_signal.emit("일반 자동 입찰입니다...................")

            fired = _adaptive_wait(target_time)   # 마감 시각까지 정밀 대기
            if not fired:
                self.auction_operation_signal.emit("작업이 중단되었습니다.")
                if _timer_period_set:
                    ctypes.windll.winmm.timeEndPeriod(1)
                return

            now = datetime.now()          # 실제 입찰 시각 기록
            self.refresh(browser, True)   # 페이지 새로고침 + 최신 가격으로 입찰 제출
            end = datetime.now()          # 입찰 처리 완료 시각 기록
            self.bidding(browser)         # 결과 확인창 닫기

        # ── Windows 타이머 해상도 원상복구 ──────────────────────────────────
        if _timer_period_set:
            ctypes.windll.winmm.timeEndPeriod(1)
            # 시스템 전체에 영향을 주므로 사용 후 반드시 되돌려야 함

        # ── 입찰 결과 분석 및 화면 출력 ─────────────────────────────────────
        sec = (end - now)         # 버튼 클릭부터 처리 완료까지 걸린 시간
        result = str(sec)
        browser.switch_to.window(handlers[0])   # 원래 상품 페이지로 창 전환
        click_time = result[6:]   # "0:00:00.123456" 형식에서 초 이후 부분만 추출

        # 한도 초과로 입찰을 포기한 경우
        if self.over_limit:
            self.auction_operation_signal.emit("입찰 금액이 한도를 초과하여서 입찰을 취소합니다.")
            self.auction_bid_results.emit(["한도 초과 : 입찰 취소", target_time, bidprice])
            return

        # 입찰 타이밍 정보 화면 출력
        self.auction_operation_signal.emit(f"마감 설정 시간 : {target_time}")
        self.auction_operation_signal.emit(f"PC 입찰 시간: {now}")
        self.auction_operation_signal.emit(f"입찰 클릭 처리 시간: {end}")

        # 옥션 서버에 등록된 입찰 정보 확인
        nameID, bidder_time_text = self.competition_ID_check(browser)
        # nameID       : 현재 1위 입찰자 아이디
        # bidder_time_text : 서버에 등록된 입찰 시각

        self.auction_operation_signal.emit(f"옥션 입찰등록 시간 : {bidder_time_text}")

        # 네트워크 지연시간 = 내 PC 클릭 시각 vs 서버 등록 시각 차이
        time_difference_result = self.time_difference_calculation(bidder_time_text, now)
        self.auction_operation_signal.emit(f"옥션 네트워크 지연시간 : {time_difference_result}")

        # 내 아이디 (뒤 3자리 제거 — 서버에서 ***로 마스킹하기 때문에 맞춰서 비교)
        auctionID = self.auctionID[:-3]
        self.auction_operation_signal.emit(f"TOP1 입찰자 : {nameID} == 내 ID : {auctionID}")

        # 1위 입찰자가 나인지 확인해서 성공/실패 판단
        if nameID == auctionID:
            self.successCheck = True
            self.auction_operation_signal.emit(f"입찰에 성공하였습니다. 입찰금액 : {bidprice}")
            self.auction_bid_results.emit(
                [bidprice, now, bidprice, click_time, time_difference_result, bidder_time_text]
            )
        else:
            self.successCheck = False
            self.auction_operation_signal.emit(f"입찰에 실패하였습니다. 입찰금액 : {bidprice}")
            self.auction_bid_results.emit(
                [bidprice, now, bidprice, click_time, time_difference_result, bidder_time_text]
            )


    # ============================================================
    # startCrawling() — 상품 정보 수집 및 입찰 프로세스 시작
    # ============================================================
    def startCrawling(self, interrupted, finished=None):
        """
        로그인 완료 후 상품 페이지에서 필요한 정보를 수집하고
        입찰 대기를 시작하는 함수입니다.

        처리 순서:
          1. 상품 URL 페이지 열기
          2. 쿠키 세션 준비
          3. BeautifulSoup으로 상품 정보 파싱 (상품명, 현재가, 입찰수)
          4. 입찰 창 열기 (bidWindow)
          5. 마감 시각까지 대기 후 입찰 (check_time)
          6. 브라우저 종료 및 정리 (cleanup_resources)

        매개변수:
          interrupted : 중단 여부 확인 함수
          finished    : 작업 완료 신호
        """
        # ── 사용할 브라우저 선택 (단일/멀티스레드 구분) ──────────────────────
        if hasattr(self.local_data, "thread_data"):
            thread_id = threading.get_ident()
            browser = self.local_data.thread_data[thread_id]["browser"]
        else:
            browser = self.browser

        # ── 상품 페이지 열기 및 상태 초기화 ─────────────────────────────────
        browser.get(self.url)         # 입찰할 상품 URL로 이동
        self.successCheck = False     # 입찰 성공 여부 초기화
        self.stop_refresh = False     # 새로고침 중단 플래그 초기화
        self.over_limit = False       # 한도 초과 플래그 초기화
        self.refreshError = True      # 새로고침 오류 플래그 초기화 (True = 정상 작동 중)

        # ── 쿠키 세션 준비 ───────────────────────────────────────────────────
        # 저장된 쿠키 파일이 있으면 그것을 사용, 없으면 현재 브라우저 쿠키를 사용
        self.session = self.check_session_cookies()
        if self.session is None:
            # pkl 쿠키 파일이 없는 경우 — 현재 브라우저에서 쿠키를 직접 가져옴
            self.auction_operation_signal.emit("쿠키 파일 없음 → 현재 브라우저 세션으로 진행합니다.")
            self.session = rq.Session()
            for cookie in browser.get_cookies():
                self.session.cookies.set(
                    name=cookie['name'],
                    value=cookie['value'],
                    domain=cookie.get('domain', '.auction.co.kr')
                )

        # ── HTTP 요청으로 상품 페이지 HTML 가져오기 ──────────────────────────
        # 브라우저가 아닌 requests 라이브러리로 직접 요청 (빠르고 파싱하기 쉬움)
        try:
            res = self.session.get(self.url)   # 상품 페이지 HTML 요청
        except Exception as e:
            self.auction_operation_signal.emit(f"상품 정보 요청 실패: {e}")
            self.cleanup_resources(browser, finished)
            return

        if res.status_code != 200:
            # HTTP 상태 코드가 200이 아니면 오류 (예: 404 페이지 없음, 500 서버 오류)
            self.auction_operation_signal.emit("URL에 대한 응답이 올바르지 않습니다.")
            return

        # ── BeautifulSoup으로 HTML 파싱 ──────────────────────────────────────
        # HTML 문서를 분석해서 필요한 정보만 추출할 준비
        soup = BS(res.text, "html.parser")
        # 비유: 복잡한 신문에서 원하는 기사만 찾을 수 있도록 색인을 만드는 것

        try:
            # 상품명 추출
            title_txt = soup.select_one("div.titlev3 > h2#hdivItemTitle").text
            self.auction_bid_title.emit(title_txt)   # 화면 상단에 상품명 표시

            # 현재 입찰자 수 추출
            bid_count_text = soup.select_one("dl.nv3 dd span.fss").text
        except:
            # CSS 선택자로 요소를 찾지 못함 = URL이 올바른 옥션 상품 페이지가 아님
            self.auction_operation_signal.emit("URL이 올바르지 않습니다.")
            self.cleanup_resources(browser, finished)
            return

        # ── 입찰 가격 결정 ────────────────────────────────────────────────────
        start_price = self.biddingPrice(soup)   # 현재 입찰 가격 추출
        self.auction_operation_signal.emit(f"현재 입찰 가격 : {start_price}")

        if self.fixedplug:
            # 고정가 모드: 미리 설정한 가격 목록에서 첫 번째 값 꺼내기
            bidprice = self.fixedPricelst.pop(0)   # pop(0) = 맨 앞 값 꺼내고 목록에서 제거
            self.auction_operation_signal.emit(f"고정 입찰 가격 : {bidprice}")
        else:
            # 일반 모드: 현재가 + 추가금액 = 실제 입찰가
            bidprice = start_price + self.AdditionalAmount
            self.auction_operation_signal.emit(f"신청 입찰 가격 : {bidprice}")

        self.auction_operation_signal.emit(f"입찰자 수 : {bid_count_text}")

        # ── 디버그용 스크린샷 저장 ────────────────────────────────────────────
        # 문제 발생 시 어느 단계에서 오류가 났는지 확인하기 위한 캡처 이미지
        browser.save_screenshot("debug_screenshot.png")   # 상품 페이지 상태

        # 마감 시각 문자열을 datetime 객체로 변환
        target_time = self.wait_for_event(self.closing_time)

        browser.save_screenshot("debug_screenshot1.png")  # 입찰 창 열기 직전 상태

        # 입찰 창 열기 ([입찰하기] 버튼 클릭 → 팝업 창)
        handlers = self.bidWindow(browser)

        browser.save_screenshot("debug_screenshot2.png")  # 입찰 창 열린 후 상태

        if handlers:
            # 입찰 창이 정상적으로 열렸으면 별도 스레드에서 타이밍 대기 시작
            # 별도 스레드를 쓰는 이유: 대기 중에도 GUI가 응답할 수 있도록 하기 위함
            thread = threading.Thread(
                target=self.check_time,
                args=(target_time, bidprice, handlers, interrupted, browser)
            )
            thread.start()    # 타이밍 대기 스레드 시작
            thread.join()     # 입찰이 완전히 끝날 때까지 여기서 기다림

        # 모든 작업 완료 후 정리
        self.cleanup_resources(browser, finished)


    # ============================================================
    # cleanup_resources() — 사용한 자원 정리 및 종료
    # ============================================================
    def cleanup_resources(self, browser, finished):
        """
        입찰이 끝난 후 사용한 자원들을 깔끔하게 정리합니다.

        정리 내용:
          1. 결과 메시지 화면 출력 (성공/실패)
          2. 브라우저(Chrome) 종료
          3. 인터넷 세션(requests) 종료
          4. GUI에 "작업 완료" 신호 전송

        비유: 경매가 끝난 후 짐을 챙기고 경매장을 나가는 것
        """
        # 입찰 성공/실패에 따라 다른 메시지 출력
        if self.successCheck:
            self.auction_operation_signal.emit(f"정상 종료 되었습니다..")
        else:
            self.auction_operation_signal.emit(f"입찰이 실패했거나 취소되었습니다. 다시 시작해주세요.")

        try:
            browser.quit()       # 크롬 브라우저 완전 종료 (창 닫기 + 프로세스 종료)
            self.session.close() # 인터넷 연결 세션 종료
        except Exception as e:
            self.auction_operation_signal.emit(f"종료에러 : {e}")
            # 브라우저가 이미 닫혀있는 경우 등 예외 발생 시 오류 메시지만 출력

        # GUI에 "모든 작업이 끝났어요" 신호 전송 → 화면의 버튼 상태 복구 등
        if finished:
            finished.emit(False)
