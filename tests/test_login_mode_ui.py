import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication
import ViewController.ViewController as view_module


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(view_module, 'data_path', lambda name: tmp_path/name)
    monkeypatch.setattr(view_module, 'migrate_legacy_files', lambda: [])
    monkeypatch.setattr(view_module, 'get_password', lambda user: 'local-test-password' if user == 'selected-account' else None)
    monkeypatch.setattr(view_module, 'load_browser_bundle', lambda: SimpleNamespace(version='mock'))
    monkeypatch.setattr(view_module, 'save_config', lambda data:
                        (tmp_path/'config.json').write_text(json.dumps(data), encoding='utf-8'))
    (tmp_path/'account_data.json').write_text(json.dumps([{'id': 'selected-account'}, {'id': 'other-account'}]), encoding='utf-8')
    window = view_module.ViewController()
    window.ui.linUrl.setText('https://www.auction.co.kr/mock')
    window.ui.linMaxPrice.setText('13000')
    window.ui.linAdditionalPrice.setText('1000')
    window.setcloseTime = lambda text: ('', datetime.now()+timedelta(minutes=5))
    errors = []
    window.view_message = errors.append
    window.show()
    app.processEvents()
    yield window, errors, tmp_path
    window.close()
    app.processEvents()


def test_radio_buttons_are_exclusive_and_auto_uses_selected_account(window):
    view, errors, path = window
    assert view.manualLogin.isChecked() and not view.autoLogin.isChecked()
    view.ui.linID.setText('typed-other-id')
    view.ui.listAccount.setCurrentRow(0)
    view.autoLogin.setChecked(True)
    assert not view.manualLogin.isChecked() and view.ui.linID.isReadOnly()
    assert view.ui.btnLoginDone.isHidden()
    specs = []
    view.start_crawling.connect(lambda data, times: specs.extend(data))
    view.startBidding()
    assert not errors and specs[0].automatic_login
    assert specs[0].account_id == 'selected-account'
    config = (path/'config.json').read_text(encoding='utf-8')
    assert json.loads(config)['loginMode'] == 'automatic'
    assert 'local-test-password' not in config


def test_auto_requires_selection_and_stored_password(window):
    view, errors, path = window
    view.autoLogin.setChecked(True)
    view.startBidding()
    assert errors and '선택' in errors[-1]
    view.ui.listAccount.setCurrentRow(1)
    view.startBidding()
    assert '비밀번호' in errors[-1]


def test_manual_mode_and_longer_progress_history(window):
    view, errors, path = window
    view.autoLogin.setChecked(True)
    view.manualLogin.setChecked(True)
    assert not view.autoLogin.isChecked() and not view.ui.linID.isReadOnly()
    assert not view.ui.btnLoginDone.isHidden()
    view.ui.linID.setText('manual-account')
    specs = []
    view.start_crawling.connect(lambda data, times: specs.extend(data))
    view.startBidding()
    assert not errors and specs[0].automatic_login is False
    for i in range(45):
        view.viewstatusList(f'입찰 진행 {i}')
    assert view.ui.listProgress.count() == 45
    assert '입찰 진행 0' in view.ui.listProgress.item(0).text()
