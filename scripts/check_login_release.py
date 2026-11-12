"""Check the packaged login fix; never start a browser or submit a bid."""
import json
import os
from pathlib import Path
import subprocess
import time
from types import CodeType

from PyInstaller.archive.readers import CArchiveReader


def main():
    root = Path(__file__).resolve().parents[1]
    release = root / 'dist' / 'login-click-fix' / 'main'
    executable = release / 'main.exe'
    archive = CArchiveReader(str(executable)).open_embedded_archive('PYZ.pyz')
    code = archive.extract('auction_login')
    functions = {c.co_name: c for c in code.co_consts if isinstance(c, CodeType)}
    assert '_settle_login_button' in functions
    assert any(isinstance(c, str) and 'document.activeElement' in c
               for c in functions['_settle_login_button'].co_consts)
    assert 8_000_000_000 in functions['automatic_login'].co_consts

    # Carry forward allowed UI settings and account IDs only, never passwords.
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    allowed = {'url', 'maxPrice', 'additionalPrice', 'fixedPrice', 'auctionID',
               'manualOffsetMs', 'closingTime', 'auctionRegTime', 'range1',
               'range2', 'range3', 'clickTime1', 'clickTime2', 'clickTime3'}
    safe = {k: v for k, v in config.items() if k in allowed}
    safe['loginMode'] = 'manual'
    (release / 'config.json').write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding='utf-8')
    accounts = json.loads((root / 'account_data.json').read_text(encoding='utf-8'))
    (release / 'account_data.json').write_text(json.dumps([{'id': row['id']} for row in accounts],
        ensure_ascii=False, indent=2), encoding='utf-8')
    check = release / 'package_check.json'
    subprocess.run([str(executable), '--self-test-report', str(check)], check=True, timeout=30)
    report = json.loads(check.read_text(encoding='utf-8'))
    assert report['build'] == 'login-click-fix-2026-11-12'
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    process = subprocess.Popen([str(executable)], cwd=release, env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        time.sleep(4)
        assert process.poll() is None, 'GUI exited during startup'
    finally:
        if process.poll() is None:
            process.terminate()  # Only this diagnostic's own process.
        process.wait(timeout=10)
    report.update(gui_startup_passed=True, packaged_login_fix_present=True,
                  real_bid_attempted=False, live_login_confirmed=False,
                  live_login_limitation='site_bot_check_not_completed')
    check.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
