"""Render the real Qt view using dummy data in a build-only directory."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QFontDatabase, QFont
import ViewController.ViewController as view_module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['automatic', 'manual'], default='manual')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'build' / 'login-mode-preview'
    root.mkdir(parents=True, exist_ok=True)
    (root/'account_data.json').write_text(json.dumps([{'id':'selected-account'}]), encoding='utf-8')
    view_module.data_path = lambda name: root/name
    view_module.migrate_legacy_files = lambda: []
    view_module.get_password = lambda account: 'local-test-password'
    view_module.save_config = lambda values: None
    app = QApplication([])
    # The offscreen Qt plugin has no system font database in the sandbox.
    # Load real Windows glyphs explicitly for the preview only.
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgunbd.ttf')
    app.setFont(QFont('Malgun Gothic', 9))
    view = view_module.ViewController()
    for widget in view.findChildren(QWidget):
        font = widget.font()
        font.setFamily('Malgun Gothic')
        widget.setFont(font)
    view.setWindowTitle('옥션 · 로그인 방식/진행 로그 수정본')
    view.ui.linUrl.setText('https://www.auction.co.kr/mock')
    view.ui.linID.setText('selected-account')
    view.ui.linPW.setText('local-test-password')
    view.ui.listAccount.setCurrentRow(0)
    view.ui.linMaxPrice.setText('13000')
    view.ui.linAdditionalPrice.setText('1000')
    view.view_bidTitle('로컬 시험 상품 / 표시 예시')
    (view.autoLogin if args.mode == 'automatic' else view.manualLogin).setChecked(True)
    if args.mode == 'manual':
        view.enableLoginDoneBtn()
    for message in ['[시험] 입찰 작업 시작: 총 1건',
                    '[시험] ' + ('자동 로그인·창 숨김' if args.mode == 'automatic' else '수동 로그인·창 표시'),
                    '[시험] 로그인 확인 완료! 입찰 준비를 시작합니다.',
                    '[시험] 상품명: 로컬 시험 상품 / 표시 예시',
                    '[시험] 현재 입찰 가격: 13,000원',
                    '[시험] 입찰자 수: 4명',
                    '[시험] 입찰 준비 완료. 예약 시각을 확인합니다.',
                    '[시험] 최신 현재가: 13,000원 + 추가 금액: 1,000원',
                    '[시험] 계산 입찰가: 14,000원 / 금액 한도: 13,000원',
                    '[시험] 입찰가가 한도를 초과해 제출하지 않았습니다.',
                    '[시험] 입찰 결과: 한도 초과로 미제출',
                    '[시험] PC 입찰 클릭 시각: 확인 불가',
                    '[시험] 이번 제출의 서버 등록시각: 미확인']:
        view.viewstatusList(message)
    view.viewbid_results(['over_limit', None, None, None, None, None])
    view.show()
    app.processEvents()
    output = root/f'{args.mode}.png'
    view.grab().save(str(output))
    print(output)
    view.close()


if __name__ == '__main__':
    main()
