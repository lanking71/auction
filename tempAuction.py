import threading
import time

import requests as rq
from selenium.common import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup as BS

from datetime import datetime
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox
from multiprocessing import Process


class Auction(QObject):
    auction_operation_signal = Signal(str)
    auction_bid_results = Signal(list)
    auction_bid_title = Signal(str)

    def __init__(self):
        super().__init__()

    def fixedMultipleBid(self, closing_time, interrupted, finished):
        def process_task(closing_time, interrupted, finished):
            self.closing_time = closing_time
            self.setupbrowser()
            if self.loginstart(finished):
                self.startCrawling(interrupted, finished)

        params_list = [(closing_time, interrupted, finished), (closing_time, interrupted, finished),
                       (closing_time, interrupted, finished), (closing_time, interrupted, finished)]

        processes = []
        for params in params_list:
            process = Process(target=process_task, args=params)
            processes.append(process)
            process.start()

        for process in processes:
            process.join()

    def auctionStart(self, startData, closing_time, interrupted, finished=None):
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
        else:
            self.fixedplug = True
            self.maxPrice = 0
            self.AdditionalAmount = 0
            self.fixedPrice = int(startData[1])
            self.auctionID = startData[2]
            self.auctionPW = startData[3]

        self.closing_time = closing_time

        self.setupbrowser()
        if self.loginstart(finished):
            self.startCrawling(interrupted, finished)

    def message_view(self, msg):
        msgstr = QMessageBox()
        msgstr.setWindowTitle("알림")
        msgstr.setText(msg)
        msgstr.exec()

    def setupbrowser(self):
        # 크롬드라이버 경로 지정
        service = Service(executable_path='chromedriver.exe')

        UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        options = Options()
        options.add_argument(f"--user-agent={UA}")
        options.add_argument("--window-size=800x600")  # 브라우저 창의 크기
        # options.add_argument("no-sandbox")
        options.add_argument("--headless")  # 이 부분을 추가
        options.add_argument("--blink-settings=imagesEnabled=false")  # 이미지를 로딩하지 않음..
        options.add_argument("--disable-extensions")  # 브라우저의 확장 기능을 모두 비활성화 한다.
        options.add_argument("--disable-gpu")  # GPU 가속이 웹드라이버ㅣ 성능을 저하 시킬수 있다..
        options.add_argument(
            "--disable-dev-shm-usage")  # 브라우저는 /dev/shm을 사용하여 리소스를 공유하지만, 이 영역의 크기가 충분하지 않을 경우 문제가 발생할 수 있습니다.
        # options.add_experimental_option("prefs", {"disk-cache-size": 4096}) #웹 페이지 캐싱 비활성화
        # options.add_experimental_option("detach", True)
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        # self.browser = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        self.browser = webdriver.Chrome(service=service, options=options)
        self.browser.implicitly_wait(5)

    def loginstart(self, finished):

        self.auction_operation_signal.emit("옥션 로그인을 시도 하고 있습니다.")
        try:
            self.browser.get("http://www.auction.co.kr/")
            login_button = WebDriverWait(self.browser, 5).until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "a[href='https://memberssl.auction.co.kr/authenticate/']")))
            login_button.click()

            username = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id='id']")))
            username.send_keys(self.auctionID)

            password = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id='password']")))
            password.send_keys(self.auctionPW)

            login_submit = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button[type='submit']")))
            login_submit.click()

            # Improved login check logic
            second_li_text_element = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.usermenu li:nth-child(1)")))
            second_li_text = second_li_text_element.text

            if "로그인" not in second_li_text:
                self.auction_operation_signal.emit(f"옥션 아디이 : {self.auctionID} 로그인 하였습니다..")
                self.session = rq.session()
                for cookie in self.browser.get_cookies():
                    self.session.cookies.set(cookie['name'], cookie['value'])
                return True
            else:
                raise WebDriverException(
                    "Login Failed")  # Using an exception to handle login failure for better traceability.

        except TimeoutException:
            self.auction_operation_signal.emit("로그인 시간지연으로 실패하였습니다.")
            if finished:
                finished.emit(False)
            self.browser.close()
        except (NoSuchElementException, WebDriverException) as e:
            self.auction_operation_signal.emit("로그인 중 에러가 발생하여 다시 '입찰시작' 버튼을 클릭해 주세요.")
            if finished:
                finished.emit(False)
            self.browser.close()

        return False

    def bidWindow(self):
        script = "document.getElementById('ucControls_btn1').click();"
        self.browser.execute_script(script)

        try:
            handlers = self.browser.window_handles
            self.browser.switch_to.window(handlers[1])
        except Exception as e:
            self.auction_operation_signal.emit(f"입찰을 진행할 수 없는 계정이거나 입찰이 이미 종료되어 오류가 발생하였습니다.")
            return False
        return handlers

    def fixedbid(self):
        self.browser.execute_script("document.querySelector('input#buttonBid').click();")

    def refresh(self, last=False):
        self.browser.refresh()
        if self.refreshError:
            try:
                # 선택자를 미리 변수로 선언
                price_selector = "tbody > tr:nth-of-type(1) > td:nth-of-type(1) > .price" if self.AdditionalAmount > 0 else 'b.name span.price'
                price_element_text = self.browser.find_element(By.CSS_SELECTOR, price_selector).text
                price_data = int(price_element_text.replace(',', '').replace('원', ''))
                price = price_data + self.AdditionalAmount
                if price <= self.maxPrice:
                    if last:
                        # 필요한 숨겨진 필드들의 값을 가져옵니다.
                        viewstate_value = self.browser.find_element(By.ID, "__VIEWSTATE").get_attribute('value')
                        eventtarget_value = "buttonBid"  # 폼을 제출하는 버튼의 ID나 이름을 이곳에 설정합니다.
                        eventargument_value = ""  # 추가적인 인수가 필요하면 여기에 값을 설정합니다.

                        combined_script = f"""
                        document.querySelector('#ctrlPrice').value = '{price}';
                        document.querySelector('#__VIEWSTATE').value = '{viewstate_value}';
                        document.querySelector('#__EVENTTARGET').value = '{eventtarget_value}';
                        document.querySelector('#__EVENTARGUMENT').value = '{eventargument_value}';
                        __doPostBack('{eventtarget_value}', '{eventargument_value}');
                        """
                        self.browser.execute_script(combined_script)
                    else:
                        input_element = WebDriverWait(self.browser, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "#ctrlPrice")))
                        input_element.clear()
                else:
                    if not self.fixedplug:
                        self.over_limit = True
            except Exception as e:
                self.refreshError = False
                self.auction_operation_signal.emit(
                    f"입찰 새로고침 에러가 발생했습니다. \n 안전하게 'ALL Chrome Kill' 버튼을 클릭하여 모든 브라우저를 종료한 후 \n '입찰시작' 버튼을 클릭해 주세요.")
                try:
                    error_element = self.browser.find_element(By.CSS_SELECTOR, "#ErrorMsg")
                    error_message = error_element.text
                    if "이미 낙찰 범위에" in error_message:
                        self.auction_operation_signal.emit("이미 낙찰 범위에 계시기 때문에 입찰하실 수 없습니다.")
                        close_button = self.browser.find_element(By.CSS_SELECTOR, "#bottombutton img")
                        close_button.click()
                except:  # 요소를 찾을 수 없는 경우
                    pass

    def bidding(self):
        try:
            alert = self.browser.switch_to.alert
            alert.accept()
        except:
            pass
        close_button = self.browser.find_element(By.CSS_SELECTOR, "#bottombutton img")
        close_button.click()

    def biddingPrice(self, soup):
        # 시작가격 추출
        start_price = soup.select_one(".redprice .present_price .present_num").text.replace(',', '')
        return int(start_price)

    def competition_ID_check(self):
        auction_record_link = self.browser.find_element(By.CSS_SELECTOR, "a[href^='javascript:checkEnd']")

        auction_record_link.click()

        bidder_id_element = self.browser.find_element(By.CSS_SELECTOR, ".bid_tbl2 tr:nth-child(2) td.bidid")
        bidder_id_text = bidder_id_element.text

        bidder_time_element = self.browser.find_element(By.CSS_SELECTOR, ".bid_tbl2 tr:nth-child(2) td:nth-child(2)")
        bidder_time_text = bidder_time_element.text

        # '***' 부분을 제거하여 'lanki' 만 추출합니다.
        bidder_id_clean = bidder_id_text.replace('***', '')
        self.browser.back()
        return bidder_id_clean, bidder_time_text

    def wait_for_event(self, target_time_str):
        target_time = datetime.strptime(target_time_str, '%y-%m-%d %H:%M:%S.%f')
        return target_time

    def time_difference_calculation(self, new_target_time, now1):
        time_difference = datetime.strptime(new_target_time, '%Y-%m-%d %H:%M:%S.%f')
        time_difference_result = abs((time_difference - now1).total_seconds())

        return time_difference_result

    def check_time(self, target_time, bidprice, handlers, interrupted, interval=0.0001):
        self.refresh()
        try:
            input_element = WebDriverWait(self.browser, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#ctrlPrice")))
            input_element.clear()
        except Exception as e:
            self.auction_operation_signal.emit("입찰금액 입력폼에 문제 발생..")
            return

        if self.fixedplug:
            self.auction_operation_signal.emit("고정 금액 입찰입니다..................")
            input_element.send_keys(bidprice)
            while True:
                if interrupted():
                    self.auction_operation_signal.emit("작업이 중단되었습니다.")
                    return
                now = datetime.now()
                if now >= target_time:
                    self.fixedbid()
                    end = datetime.now()
                    self.bidding()
                    break
                time.sleep(interval)
        else:
            self.auction_operation_signal.emit("일반 자동 입찰입니다...................")
            while True:
                if interrupted():
                    self.auction_operation_signal.emit("작업이 중단되었습니다.")
                    return
                now = datetime.now()
                if now >= target_time:
                    self.refresh(True)
                    end = datetime.now()
                    self.bidding()
                    break
                time.sleep(interval)

        sec = (end - now)
        result = str(sec)
        self.browser.switch_to.window(handlers[0])
        click_time = result[6:]
        if self.over_limit:
            self.auction_operation_signal.emit("입찰 금액이 한도를 초과하여서 입찰을 취소합니다.")
            self.auction_bid_results.emit(["한도 초과 : 입찰 취소", target_time, bidprice])
            return
        self.auction_operation_signal.emit(f"마감 설정 시간 : {target_time}")
        self.auction_operation_signal.emit(f"PC 입찰 시간: {now}")
        self.auction_operation_signal.emit(f"입찰 클릭 처리 시간: {end}")

        nameID, bidder_time_text = self.competition_ID_check()
        self.auction_operation_signal.emit(f"옥션 입찰등록 시간 : {bidder_time_text}")
        time_difference_result = self.time_difference_calculation(bidder_time_text, now)
        self.auction_operation_signal.emit(f"옥션 네트워크 지연시간 : {time_difference_result}")
        auctionID = self.auctionID[:-3]
        self.auction_operation_signal.emit(f"TOP1 입찰자 : {nameID} == 내 ID : {auctionID}")
        if nameID == auctionID:
            self.successCheck = True
            self.auction_operation_signal.emit(f"입찰에 성공하였습니다. 입찰금액 : {bidprice}")
            self.auction_bid_results.emit(
                [bidprice, now, bidprice, click_time, time_difference_result, bidder_time_text])
        else:
            self.successCheck = False
            self.auction_operation_signal.emit(f"입찰에 실패하였습니다. 입찰금액 : {bidprice}")
            self.auction_bid_results.emit(
                [bidprice, now, bidprice, click_time, time_difference_result, bidder_time_text])

    def startCrawling(self, interrupted, finished):
        self.browser.get(self.url)
        self.successCheck = False
        self.stop_refresh = False
        self.over_limit = False
        self.refreshError = True

        res = self.session.get(self.url)
        if res.status_code != 200:
            self.auction_operation_signal.emit("URL에 대한 응답이 올바르지 않습니다.")
            return
        soup = BS(res.text, "html.parser")

        try:
            title_txt = soup.select_one("div.titlev3 > h2#hdivItemTitle").text
            self.auction_bid_title.emit(title_txt)
            # 입찰수 추출
            bid_count_text = soup.select_one("dl.nv3 dd span.fss").text
            # 입찰가격 추출
        except:
            self.auction_operation_signal.emit("URL이 올바르지 않습니다.")
            self.cleanup_resources(finished)
            return

        start_price = self.biddingPrice(soup)
        self.auction_operation_signal.emit(f"현재 입찰 가격 : {start_price}")
        if self.fixedplug:
            bidprice = self.fixedPrice
            self.auction_operation_signal.emit(f"고정 입찰 가격 : {bidprice}")
        else:
            bidprice = start_price + self.AdditionalAmount  # 입찰가격 시작가격
            self.auction_operation_signal.emit(f"신청 입찰 가격 : {bidprice}")

        self.auction_operation_signal.emit(f"입찰자 수 : {bid_count_text}")

        # 남은시간 추출
        target_time = self.wait_for_event(self.closing_time)
        handlers = self.bidWindow()
        if handlers:
            thread = threading.Thread(target=self.check_time, args=(target_time, bidprice, handlers, interrupted))
            thread.start()
            thread.join()

        self.cleanup_resources(finished)

    def cleanup_resources(self, finished):
        if self.successCheck:
            self.auction_operation_signal.emit(f"정상 종료 되었습니다..")
        else:
            self.auction_operation_signal.emit(f"입찰이 실패했거나 취소되었습니다. 다시 시작해주세요.")
        try:
            self.browser.quit()
            self.session.close()
        except Exception as e:
            self.auction_operation_signal.emit(f"종료에러 : {e}")
        if finished:
            finished.emit(False)

