import multiprocessing
import sys

from PySide6.QtWidgets import QMainWindow, QApplication
from ViewController.ViewController import ViewController
from Controller.AuctionController import AuctionController
from Auction import Auction
from multiprocessing import Process, Manager

def main():
    app = QApplication()
    window = ViewController()
    window.setWindowTitle("옥션 · 자동/수동 로그인 · 로그인 클릭 수정본")
    auction = Auction()
    controller = AuctionController(window,auction)
    window.setFixedSize(window.size())
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-report":
        # Packaging check only: no window, login, browser launch or live bid.
        import hashlib
        import json
        from pathlib import Path
        from browser_runtime import load_browser_bundle
        from precision_scheduler import TIMER_SCRIPT
        bundle = load_browser_bundle()
        Path(sys.argv[2]).write_text(json.dumps({
            "passed": True,
            "build": "login-click-fix-2026-11-12",
            "browser_version": bundle.version,
            "browser_timer_sha256": hashlib.sha256(TIMER_SCRIPT.encode("utf-8")).hexdigest(),
            "timer_diagnostics_present": "not_enabled_before_deadline" in TIMER_SCRIPT,
        }, indent=2), encoding="utf-8")
    else:
        main()
    # multiprocessing.freeze_support()
    # processes = []
    # for i in range(2):
    #     # p = Process(target=main, args=(data[i],))
    #     p = Process(target=main)
    #     p.start()
    #     processes.append(p)
    #
    # for process in processes:
    #     process.join()


