import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from concurrent.futures import ThreadPoolExecutor

import browser_runtime
from browser_runtime import BrowserBundleError, EXPECTED_VERSION, load_browser_bundle


def test_missing_bundle_is_blocked(tmp_path: Path):
    manifest = tmp_path / "browser_manifest.json"
    manifest.write_text(json.dumps({
        "version": EXPECTED_VERSION,
        "chrome": "missing/chrome.exe",
        "driver": "missing/chromedriver.exe",
        "verified": True,
    }), encoding="utf-8")
    with pytest.raises(BrowserBundleError, match="없습니다"):
        load_browser_bundle(manifest, verify_binaries=False)


def test_unverified_version_is_blocked(tmp_path: Path):
    manifest = tmp_path / "browser_manifest.json"
    manifest.write_text(json.dumps({"version": "1.2.3.4", "chrome": "x", "driver": "y"}), encoding="utf-8")
    with pytest.raises(BrowserBundleError, match="검증되지 않은"):
        load_browser_bundle(manifest, verify_binaries=False)


def test_none_process_output_is_reported_as_bundle_error(tmp_path: Path, monkeypatch):
    binary = tmp_path / "binary.exe"
    binary.write_bytes(b"not a real executable")
    monkeypatch.setattr(browser_runtime, "_windows_file_version", lambda _path: None)
    monkeypatch.setattr(
        browser_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=None, stderr=None),
    )
    with pytest.raises(BrowserBundleError, match="버전 문자열"):
        browser_runtime._binary_version(binary)


def test_driver_copy_is_private_for_every_browser(tmp_path, monkeypatch):
    original = tmp_path / "original.exe"
    original.write_bytes(b"verified driver")
    bundle = browser_runtime.BrowserBundle(EXPECTED_VERSION, original, original)
    monkeypatch.setattr(browser_runtime, "data_root", lambda: tmp_path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        paths = list(pool.map(lambda _: browser_runtime.writable_driver_copy(bundle), range(12)))
    assert len(set(paths)) == 12
    paths[0].write_bytes(b"UC patched copy")
    assert original.read_bytes() == b"verified driver"
    assert all(p.read_bytes() == b"verified driver" for p in paths[1:])
    browser_runtime._remove_driver_copy(paths[0])
    assert not paths[0].parent.exists()
    assert all(p.exists() for p in paths[1:])


def test_owned_browser_cleanup_does_not_touch_another_session(tmp_path):
    own = tmp_path / "own" / "chromedriver.exe"
    other = tmp_path / "other" / "chromedriver.exe"
    for path in [own, other]:
        path.parent.mkdir()
        path.write_bytes(b"driver")
    def fail_quit():
        raise RuntimeError("injected quit failure")
    browser = browser_runtime._OwnedBrowser(SimpleNamespace(quit=fail_quit, session_id="owned"), own)
    assert browser.session_id == "owned"
    with pytest.raises(RuntimeError):
        browser.quit()
    assert not own.exists() and other.exists()


def test_application_and_uc_finalizer_only_quit_native_driver_once(tmp_path):
    directory = tmp_path / "session"
    directory.mkdir()
    path = directory / "chromedriver.exe"
    path.write_bytes(b"driver")
    calls = []
    native = SimpleNamespace(quit=lambda: calls.append(True))
    owned = browser_runtime._OwnedBrowser(native, path)
    owned.quit()
    native.quit()  # Same path used by the UC destructor.
    owned.quit()
    assert calls == [True] and not path.exists()


def test_headless_remains_enabled_when_standard_driver_fallback_is_used(tmp_path, monkeypatch):
    from selenium import webdriver
    import undetected_chromedriver as uc
    original = tmp_path/'original.exe'
    original.write_bytes(b'original verified bundle')
    bundle = browser_runtime.BrowserBundle(EXPECTED_VERSION, original, original)
    monkeypatch.setattr(browser_runtime, 'load_browser_bundle', lambda: bundle)
    monkeypatch.setattr(browser_runtime, 'data_root', lambda: tmp_path)
    observed = []
    def broken_uc(**kwargs):
        observed.append(('uc', kwargs['options'].arguments))
        assert kwargs['version_main'] == int(EXPECTED_VERSION.split('.')[0])
        raise RuntimeError('injected UC startup failure')
    def standard(**kwargs):
        observed.append(('standard', kwargs['options'].arguments))
        return SimpleNamespace(quit=lambda: None)
    monkeypatch.setattr(uc, 'Chrome', broken_uc)
    monkeypatch.setattr(webdriver, 'Chrome', standard)
    browser, degraded = browser_runtime.create_browser(headless=True)
    try:
        assert degraded
        assert all('--headless=new' in args for _, args in observed)
    finally:
        browser.quit()
