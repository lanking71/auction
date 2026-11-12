import traceback

from PySide6.QtCore import Signal,QObject,QRunnable,QThreadPool
import dill

class WorkerSignals(QObject):
    save_task_page = Signal(int)
    finished_signal = Signal(bool)

class Worker(QRunnable):

    def __init__(self, func,*args,**kwargs):
        super(Worker, self).__init__()
        dill.settings['recurse'] = True
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signal = WorkerSignals()
        self.kwargs["finished"] = self.signal.finished_signal
        self.is_interrupted = False

    def run(self):
        try:
            self.is_running = True
            self.kwargs['interrupted'] = self.check_interrupted
            self.func(*self.args, **self.kwargs)
        except Exception as e:
            print(f"Error in worker thread: {e}")
            traceback.print_exc()
        finally:
            self.is_running = False
            self.signal.finished_signal.emit(False)

    def check_interrupted(self):
        return self.is_interrupted

    def stop(self):
        self.is_interrupted = True


class AuctionController(QObject):
    isWorkRunning_signal = Signal(bool)

    def __init__(self,view,auction):
        super().__init__()

        self.view = view
        self.crawling = auction
        self.view.start_crawling.connect(self.auctionStart)
        self.view.stop_crawling.connect(self.auctionStop)
        self.crawling.auction_operation_signal.connect(self.viewstatusList)
        self.crawling.compensation_updated_signal.connect(self.view.updateAutomaticOffset)
        self.crawling.schedule_updated_signal.connect(self.view.updateExecutionSchedule)
        self.crawling.auction_bid_results.connect(self.viewbid_results)
        self.crawling.auction_bid_title.connect(self.view_bidTitle)
        # self.view.stop_session_signal.connect(self.auctionStop_session)
        self.isWorkRunning_signal.connect(self.view_isWorkRun)

        # ── 수동 로그인 연결 ─────────────────────────────────────────────────
        # Auction이 로그인 필요 신호 → ViewController 버튼 활성화
        self.crawling.login_needed_signal.connect(self.view.enableLoginDoneBtn)
        # ViewController 버튼 클릭 → Auction 대기 이벤트 해제
        self.view.login_complete_signal.connect(self.crawling.trigger_manual_login)
        # ─────────────────────────────────────────────────────────────────────

    def view_bidTitle(self,msgStr):
        self.view.view_bidTitle(msgStr)

    def view_isWorkRun(self,isRun):
        self.view.setThreadStatus(isRun)

    def viewbid_results(self,lst):
        self.view.viewbid_results(lst)

    def auctionStop(self,stop):
        if stop and hasattr(self,'worker'):
            self.worker.stop()
            self.crawling.cancel_all()
            self.crawling.auction_operation_signal.emit("취소 요청을 전달했습니다. 작업별 자원을 정리하는 중입니다.")


    def auctionStart(self,startData,secondsWindow):
        thread_pool = QThreadPool.globalInstance()
        # Worker owns the single completion signal, including start-up failures.
        self.worker = Worker(self._run_auction,startData,secondsWindow)
        self.isWorkRunning_signal.emit(True)
        self.worker.signal.finished_signal.connect(self.view_isWorkRun)
        thread_pool.start(self.worker)
        # self.crawling.auctionStart(startData,secondsWindow)

    def _run_auction(self, data, times, interrupted, finished):
        self.crawling.auctionStart(data, times, interrupted, finished=None)

    def auctionStop_session(self,stop):
        if stop:
            self.auctionStop(True)

    def viewstatusList(self,meassgeStr):
        self.view.viewstatusList(meassgeStr)






