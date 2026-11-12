"""Exercise input/result adapters without opening windows or saving settings."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from Controller.AuctionController import Worker
from ViewController.ViewController import ViewController


class Field:
    def __init__(self, text=""):
        self.value = text
    def text(self):
        return self.value
    def setText(self, text):
        self.value = text


def test_sparse_fixed_fields_do_not_require_unused_times():
    sent, errors = [], []
    tomorrow = datetime.now()+timedelta(days=1)
    ui = SimpleNamespace(linUrl=Field("https://www.auction.co.kr/mock"), linID=Field("account"),
        oneWindow=Field("12:00:00.100"), linfixedPrice=Field("1,000"),
        linfixedPrice_2=Field("0"), linfixedPrice_3=Field("3,000"), linfixedPrice_4=Field(""),
        clickTime1=Field(""), clickTime2=Field("00.300"), clickTime3=Field(""))
    obj = SimpleNamespace(threadChk=False, ui=ui, fixedbidding=True,
        manualOffset=SimpleNamespace(value=lambda: -25),
        setcloseTime=lambda text: ("", tomorrow.replace(microsecond=300000 if text.endswith("300") else 100000)),
        view_message=errors.append, save_input_data=lambda: None,
        start_crawling=SimpleNamespace(emit=lambda specs, times: sent.extend(specs)))
    ViewController.startBidding(obj)
    assert not errors
    assert [s.price for s in sent] == [1000, 3000]
    assert [s.target_server_time.microsecond for s in sent] == [100000, 300000]
    assert all(s.manual_offset_ms == -25 for s in sent)


def test_unknown_result_does_not_require_click_timestamp():
    names = ["lbResult", "lbsuccessfulPrice", "lbresultTime", "labclick_time", "laboptimum", "lnauctionRegTime"]
    obj = SimpleNamespace(ui=SimpleNamespace(**{n: Field() for n in names}), save_input_data=lambda: None)
    ViewController.viewbid_results(obj, ["unknown", None, None, None, None, None])
    assert "불명" in obj.ui.lbResult.text() and "미검증" in obj.ui.laboptimum.text()


def test_worker_signals_completion_even_on_failure(capsys):
    def fail(**kwargs):
        raise RuntimeError("injected worker failure")
    worker = Worker(fail)
    finished = []
    worker.signal.finished_signal.connect(finished.append)
    worker.run()
    assert finished == [False] and not worker.is_running
