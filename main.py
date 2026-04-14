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
    auction = Auction()
    controller = AuctionController(window,auction)
    window.setFixedSize(window.size())
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
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


