from PySide6 import QtCore
from PySide6.QtWidgets import QMainWindow, QMessageBox,QLineEdit
from PySide6.QtCore import Qt,Signal,QObject,Slot
from ViewController.auctionUi import Ui_MainWindow
from datetime import datetime
import os
import json


class ViewController(QMainWindow,QObject):
    start_crawling = Signal(list,str)
    stop_crawling = Signal(bool)
    # stop_session_signal = Signal(bool)

    def __init__(self):
        super().__init__()

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.threadChk = False
        self.load_input_data()
        self.loadAccountsToList()
        self.bidtime = 700000
        if self.biddingTime:
            self.bidtime = int(self.biddingTime)
        current_time = datetime.now()
        new_time = current_time.replace(second=59, microsecond=self.bidtime)  # 100 milliseconds = 100,000 microseconds
        formatted_time = new_time.strftime('%H:%M:%S.%f')[:-3]
        self.ui.oneWindow.setText(formatted_time)
        self.ui.checkFixed.setChecked(False)
        self.ui.checRegMode.setChecked(False)
        self.ui.btnaccountReg.setDisabled(True)
        self.ui.linfixedPrice.setDisabled(True)
        self.ui.linfixedPrice_2.setDisabled(True)
        self.ui.linfixedPrice_3.setDisabled(True)
        self.ui.linfixedPrice_4.setDisabled(True)
        self.ui.range1.setDisabled(True)
        self.ui.range2.setDisabled(True)
        self.ui.range3.setDisabled(True)
        self.fixedbidding = False
        self.ui.checkFixed.stateChanged.connect(self.toggle_input_box)
        self.ui.checRegMode.stateChanged.connect(self.accountReg_box)
        self.ui.linPW.setEchoMode(QLineEdit.Password)
        self.ui.linMaxPrice.textChanged.connect(self.on_price_changed)
        self.ui.btncalcul.clicked.connect(self.calculationPrice)
        self.ui.linAdditionalPrice.textChanged.connect(self.on_Additional_changed)
        self.ui.linfixedPrice.textChanged.connect(lambda text=self.ui.linfixedPrice: self.on_fixedPrice_chaged(text,"fixedPrice1"))
        self.ui.linfixedPrice_2.textChanged.connect(lambda text=self.ui.linfixedPrice_2: self.on_fixedPrice_chaged(text,"fixedPrice2"))
        self.ui.linfixedPrice_3.textChanged.connect(lambda text=self.ui.linfixedPrice_3: self.on_fixedPrice_chaged(text,"fixedPrice3"))
        self.ui.linfixedPrice_4.textChanged.connect(lambda text=self.ui.linfixedPrice_4: self.on_fixedPrice_chaged(text,"fixedPrice4"))
        self.ui.BtnchromKill.clicked.connect(self.kill_all_chrome)
        self.ui.btnStart.clicked.connect(self.startBidding)
        self.ui.btnCancel.clicked.connect(self.stopBidding)
        self.ui.btnreset.clicked.connect(self.resetBidding)
        self.ui.btnaccountReg.clicked.connect(self.accountRegStart)
        self.ui.listAccount.itemClicked.connect(self.load_id_list)


    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            # selected_data = [json.loads(item.data(QtCore.Qt.UserRole)) for item in self.ui.listAccount.selectedItems()]
            selected_data = [json.loads(item.text()) for item in self.ui.listAccount.selectedItems()]
            #  파일에서 기존 데이터를 읽습니다.
            try:
                with open('account_data.json','r') as f:
                    data_list = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                data_list

            # 선택된 데이터를 기존 데이터 목록에서 제거합니다.
            for selected_item in selected_data:
                data_list = [account for account in data_list if not (account['id'] == selected_item['id'] and account['pw'] == selected_item['pw'])]

            # 변견됭 데이터를 파일에 다시 씁니다.
            with open('account_data.json','w') as f:
                json.dump(data_list, f)

            for item in self.ui.listAccount.selectedItems():
                self.ui.listAccount.takeItem(self.ui.listAccount.row(item))

    def load_id_list(self,item):
        data = json.loads(item.text())
        self.ui.linID.setText(data['id'])
        self.ui.linPW.setText(data['pw'])
        self.save_input_data()

    def loadAccountsToList(self):
        try:
            with open('account_data.json','r') as f:
                data_list = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data_list = []

        for account in data_list:
            self.ui.listAccount.addItem(json.dumps(account))

    def accountRegStart(self):
        input_field = {
            self.ui.linID:"계정 ID를 입력하세요.",
            self.ui.linPW:"계정 PW를 입력하세요."
        }
        account_data = {}
        for field,message in input_field.items():
            text_value = field.text().strip()
            if not text_value:
                self.view_message(message)
                return
            if field == self.ui.linID:
                account_data['id'] = text_value
            else:
                account_data['pw'] = text_value

        try:
            with open('account_data.json','r') as f:
                data_list = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data_list = []
        data_list.append(account_data)

        with open('account_data.json','w') as f:
            json.dump(data_list,f)

        self.ui.listAccount.addItem(json.dumps(account_data))

        # with open('accoutn_data.txt','a') as f:
        #     f.write(f"{account_data['id']} {account_data['pw']}\n")
        # self.ui.listAccount.addItem(json.dumps(account_data))

    def accountReg_box(self):
        if self.ui.checRegMode.isChecked():
            self.ui.btnaccountReg.setDisabled(False)
            self.ui.linID.clear()
            self.ui.linPW.clear()
            self.ui.linID.setFocus()
        else:
            self.ui.btnaccountReg.setDisabled(True)
            self.load_input_data()

    def toggle_input_box(self):
        if self.ui.checkFixed.isChecked():
            self.fixedbidding = True
            self.ui.linfixedPrice.setText("0")
            self.ui.linfixedPrice_2.setText("0")
            self.ui.linfixedPrice_3.setText("0")
            self.ui.linfixedPrice_4.setText("0")
            self.ui.linfixedPrice.setDisabled(False)
            self.ui.linfixedPrice_2.setDisabled(False)
            self.ui.linfixedPrice_3.setDisabled(False)
            self.ui.linfixedPrice_4.setDisabled(False)
            self.ui.range1.setDisabled(False)
            self.ui.range2.setDisabled(False)
            self.ui.range3.setDisabled(False)
            self.ui.linMaxPrice.setDisabled(True)
            self.ui.linAdditionalPrice.setDisabled(True)
        else:
            self.fixedbidding = False
            self.ui.linfixedPrice.setDisabled(True)
            self.ui.linfixedPrice_2.setDisabled(True)
            self.ui.linfixedPrice_3.setDisabled(True)
            self.ui.linfixedPrice_4.setDisabled(True)
            self.ui.range1.setDisabled(True)
            self.ui.range2.setDisabled(True)
            self.ui.range3.setDisabled(True)
            self.ui.linMaxPrice.setDisabled(False)
            self.ui.linAdditionalPrice.setDisabled(False)

    def kill_all_chrome(self):
        if self.threadChk:
            self.view_message("압찰이 실행중에 있습니다.")
        else:
            os.system("taskkill /f /im chrome.exe")
            os.system("taskkill /f /im chromedriver.exe")
            self.view_message("모든 크롬 브라우저를 종료했습니다.")

    def on_fixedPrice_chaged(self, text, input_field_name):

        input_field = {
            "fixedPrice1":self.ui.linfixedPrice,
            "fixedPrice2":self.ui.linfixedPrice_2,
            "fixedPrice3":self.ui.linfixedPrice_3,
            "fixedPrice4":self.ui.linfixedPrice_4
        }

        input_field[input_field_name].textChanged.disconnect()
        # 숫자만 추출
        clean_number = ''.join(filter(str.isdigit, text))
        # 숫자를 천 단위로 구분하여 표시
        formatted_number = '{:,}'.format(int(clean_number) if clean_number else 0)
        input_field[input_field_name].setText(formatted_number)
        input_field[input_field_name].textChanged.connect(lambda text=input_field[input_field_name]: self.on_fixedPrice_chaged(text,input_field_name))

    def calculationPrice(self):

        input_field = {
            "range1": self.ui.linfixedPrice_2,
            "range2": self.ui.linfixedPrice_3,
            "range3": self.ui.linfixedPrice_4
        }

        range_field = {
            "range1":self.ui.range1,
            "range2":self.ui.range2,
            "range3":self.ui.range3
        }
        if self.ui.linfixedPrice.text() == "0":
            self.view_message("기준 입찰가격을 입력하세요.")
            self.ui.linfixedPrice.setFocus()
            return
        rate_price = int(self.ui.linfixedPrice.text().replace(',',""))

        for item, field in range_field.items():
            if not field.text():
                self.view_message("비율을 입력하세요.")
                field.setFocus()
                return
            range_field[item] = int(field.text()) / 100
        for item, field in range_field.items():
            resultValue = rate_price + (rate_price * field)
            resultValue = round(resultValue)
            input_field[item].setText(str(resultValue))
        self.save_input_data()

    def on_Additional_changed(self, text):
        # 신호 발생시 호출될 슬롯
        # 신호를 일시적으로 끄고, 텍스트를 변경한 다음 다시 신호를 켭니다.
        # 이렇게 하지 않으면 텍스트를 변경할 때마다 이 함수가 다시 호출되어 무한 루프에 빠질 수 있습니다.
        self.ui.linAdditionalPrice.textChanged.disconnect(self.on_Additional_changed)

        # 숫자만 추출
        clean_number = ''.join(filter(str.isdigit, text))
        # 숫자를 천 단위로 구분하여 표시
        formatted_number = '{:,}'.format(int(clean_number) if clean_number else 0)
        self.ui.linAdditionalPrice.setText(formatted_number)

        self.ui.linAdditionalPrice.textChanged.connect(self.on_Additional_changed)

    def on_price_changed(self, text):
        # 신호 발생시 호출될 슬롯
        # 신호를 일시적으로 끄고, 텍스트를 변경한 다음 다시 신호를 켭니다.
        # 이렇게 하지 않으면 텍스트를 변경할 때마다 이 함수가 다시 호출되어 무한 루프에 빠질 수 있습니다.
        self.ui.linMaxPrice.textChanged.disconnect(self.on_price_changed)

        # 숫자만 추출
        clean_number = ''.join(filter(str.isdigit, text))
        # 숫자를 천 단위로 구분하여 표시
        formatted_number = '{:,}'.format(int(clean_number) if clean_number else 0)
        self.ui.linMaxPrice.setText(formatted_number)

        self.ui.linMaxPrice.textChanged.connect(self.on_price_changed)

    def view_message(self,str):
        msg = QMessageBox()
        msg.setWindowTitle("알림")
        msg.setText(str)
        msg.exec()

    def resetBidding(self):
        if self.threadChk:
            msg = QMessageBox()
            msg.setText("압찰이 실행중에 있습니다.")
            msg.exec()

        else:
            self.ui.linUrl.clear()
            self.ui.lbTitle.setText("입찰 제목  :")
            # self.ui.linStartPrice.clear()
            self.ui.linMaxPrice.clear()
            # self.ui.linAdditionalPrice.clear()
            self.ui.listProgress.clear()
            self.ui.lbResult.setText("결 과 :")
            self.ui.lbsuccessfulPrice.setText("낙찰 금액 :")
            self.ui.lbresultTime.setText("PC 입찰 클릭 시간 :")

    def view_bidTitle(self,str):
        self.ui.lbTitle.setText(f"입찰 제목  :   {str}")

    def viewbid_results(self,lst):
        self.ui.lbResult.setText(f"결 과 : {lst[0]}")
        self.ui.lbsuccessfulPrice.setText(f"낙찰 금액 : {str(lst[2])}")
        self.ui.lbresultTime.setText(f"PC 입찰 클릭 시간 : {str(lst[1].strftime('%H:%M:%S.%f'))}")
        self.ui.labclick_time.setText(f"입찰 클릭 정보통신 시간 : {str(lst[3])}")
        self.ui.laboptimum.setText(f"네트워크 전체 지연시간 : {str(lst[4])}")
        self.ui.lnauctionRegTime.setText(str(lst[5]))
        self.save_input_data()

    def stopBidding(self):
        if self.threadChk:
            self.stop_crawling.emit(True)
            self.ui.btnStart.setStyleSheet("")
            self.save_input_data()
        else:
            msg = QMessageBox()
            msg.setText("입찰이 진행하고 있지 않습니다.")
            msg.exec()

    def setThreadStatus(self,isRun):
        self.threadChk = isRun
        if self.threadChk:
            self.ui.btnStart.setStyleSheet("background-color: red;")
        else:
            self.ui.btnStart.setStyleSheet("")

    def save_input_data(self):
        input_data = {
            'url': self.ui.linUrl.text(),
            'maxPrice': self.ui.linMaxPrice.text(),
            'additionalPrice': self.ui.linAdditionalPrice.text(),
            'fixedPrice': self.ui.linfixedPrice.text(),
            'auctionID': self.ui.linID.text(),
            'auctionPW': self.ui.linPW.text(),
            'closingTime': self.ui.oneWindow.text(),
            'auctionRegTime':self.ui.lnauctionRegTime.text(),
            'range1':self.ui.range1.text(),
            'range2':self.ui.range2.text(),
            'range3':self.ui.range3.text()
        }


        with open('input_data.json','w') as file:
            json.dump(input_data, file)

    def load_input_data(self):

        try:
            with open("input_data.json",'r') as file:
                input_data = json.load(file)
            self.ui.linUrl.setText(input_data['url'])
            self.ui.linMaxPrice.setText(input_data['maxPrice'])
            self.ui.linAdditionalPrice.setText(input_data['additionalPrice'])
            self.ui.linfixedPrice.setText(input_data['fixedPrice'])
            self.ui.linID.setText(input_data['auctionID'])
            self.ui.linPW.setText(input_data['auctionPW'])
            self.ui.oneWindow.setText(input_data['closingTime'])
            self.biddingTime = input_data['closingTime'][-3:] + "000"
            self.ui.lnauctionRegTime.setText(input_data['auctionRegTime'])
            self.ui.range1.setText(input_data['range1'])
            self.ui.range2.setText(input_data['range2'])
            self.ui.range3.setText(input_data['range3'])

        except Exception as e:
            print(f"에러....{e}")
            pass
    def startBidding(self):
        if self.threadChk:
            self.view_message("입찰이 진행중입니다......")
            return
        # self.ui.btnStart.setStyleSheet("background-color: red;")
        if self.fixedbidding:
            input_fields = {
                self.ui.linfixedPrice: "고정 입찰금액을 입력하세요.",
                self.ui.oneWindow: "입찰 시작 초 설정을 입력해 주세요.",
                self.ui.linID: "옥션 ID를 입력하세요.",
                self.ui.linPW: "옥션 PW를 입력하세요."
            }
        else:
            input_fields = {
                self.ui.linUrl: "입찰 URL 정보를 입력하세요.",
                self.ui.linMaxPrice: "입찰 한도 금액을 입력하세요.",
                self.ui.oneWindow: "입찰 시자 초 설정을 입력해 주세요.",
                self.ui.linID: "옥션 ID를 입력하세요.",
                self.ui.linPW: "옥션 PW를 입력하세요."
            }
            if not self.ui.linAdditionalPrice:
                self.ui.linAdditionalPrice.setText("0")


        for field, message in input_fields.items():
            text_value = field.text().strip()

            if not text_value or text_value == "0":
                self.view_message(message)
                return

        self.save_input_data()

        # 현재 날짜와 시간 가져오기
        current_time = datetime.now()
        # 입력 필드에서 시간 데이터 가져오기
        input_time = self.ui.oneWindow.text()
        two_digit_year = current_time.year % 100
        # 입력받은 시간에 현재의 년도와 월 추가하기
        oneWindow_formatted_time = f"{two_digit_year:02}-{current_time.month:02}-{current_time.day:02} " + input_time
        if self.fixedbidding:
            start_data = [self.ui.linUrl.text(), self.ui.linfixedPrice.text().replace(',', ''), self.ui.linID.text().strip(),self.ui.linPW.text().strip()]
        else:
            start_data = [self.ui.linUrl.text(), self.ui.linMaxPrice.text().replace(',',''),self.ui.linAdditionalPrice.text().replace(',',''),self.ui.linID.text().strip(), self.ui.linPW.text().strip()]
        closing_time = oneWindow_formatted_time
        closing_time_date = datetime.strptime(closing_time,'%y-%m-%d %H:%M:%S.%f')
        current_now = datetime.now()

        # time_diff = abs((closing_time_date - current_now).total_seconds())
        time_diff = (closing_time_date - current_now).total_seconds()
        if time_diff < 1:
            self.view_message("입찰 시간을 설정을 하세요.")
            return


        self.start_crawling.emit(start_data,closing_time)

    def viewstatusList(self,meassgeStr):
        if self.ui.listProgress.count() >= 30:
            self.ui.listProgress.takeItem(0)
        self.ui.listProgress.addItem(meassgeStr)
        self.ui.listProgress.scrollToBottom()

        def process_task(self, closing_time, interrupted, finished):
            thread_index = getattr(self.local_data, f"thread_{id(threading.current_thread())}", None)
            if thread_index is None:
                thread_index = len(params_list)
                setattr(self.local_data, f"thread_{id(threading.current_thread())}", thread_index)

