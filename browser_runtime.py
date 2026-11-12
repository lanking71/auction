from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app_paths import bundle_root, data_root


EXPECTED_VERSION = "157.0.8103.38"


class BrowserBundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserBundle:
    version: str
    chrome: Path
    driver: Path
    chrome_sha256: str | None = None
    driver_sha256: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


def _windows_file_version(path: Path) -> str | None:
    """Read the PE version resource without launching the executable."""
    if os.name != "nt":
        return None
    version_dll = ctypes.windll.version
    handle = wintypes.DWORD(0)
    size = version_dll.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not version_dll.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    value = ctypes.c_void_p()
    value_size = wintypes.UINT(0)
    if not version_dll.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(value_size)):
        return None
    if value_size.value < ctypes.sizeof(_VS_FIXEDFILEINFO):
        return None
    info = ctypes.cast(value, ctypes.POINTER(_VS_FIXEDFILEINFO)).contents
    if info.dwSignature != 0xFEEF04BD:
        return None
    return ".".join(str(part) for part in (
        info.dwFileVersionMS >> 16,
        info.dwFileVersionMS & 0xFFFF,
        info.dwFileVersionLS >> 16,
        info.dwFileVersionLS & 0xFFFF,
    ))


def _binary_version(path: Path) -> str:
    file_version = _windows_file_version(path)
    if file_version:
        return file_version
    try:
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True,
                                timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BrowserBundleError(f"버전 확인 실패: {path.name}: {exc}") from exc
    output = (result.stdout or "") + (result.stderr or "")
    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", output)
    if not match:
        raise BrowserBundleError(f"버전 문자열을 읽을 수 없습니다: {path.name}")
    return match.group(1)


def load_browser_bundle(manifest_path: Path | None = None, *, verify_binaries: bool = True) -> BrowserBundle:
    manifest_path = manifest_path or bundle_root() / "browser_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrowserBundleError("앱 전용 브라우저 manifest를 읽을 수 없습니다. 앱을 다시 설치하세요.") from exc
    version = str(manifest.get("version", ""))
    chrome = bundle_root() / manifest.get("chrome", "")
    driver = bundle_root() / manifest.get("driver", "")
    if version != EXPECTED_VERSION:
        raise BrowserBundleError(f"검증되지 않은 브라우저 버전입니다: {version or '없음'}")
    if not manifest.get("verified", False):
        raise BrowserBundleError("브라우저 manifest가 릴리스 검증 완료 상태가 아닙니다.")
    if not chrome.is_file() or not driver.is_file():
        raise BrowserBundleError("앱 전용 Chrome 또는 ChromeDriver가 없습니다. 전체 배포 패키지로 다시 설치하세요.")
    bundle = BrowserBundle(version, chrome, driver, manifest.get("chrome_sha256"), manifest.get("driver_sha256"))
    if verify_binaries:
        chrome_version = _binary_version(chrome)
        driver_version = _binary_version(driver)
        if chrome_version != version or driver_version != version:
            raise BrowserBundleError(
                f"Chrome/Driver 버전 불일치: manifest={version}, chrome={chrome_version}, driver={driver_version}"
            )
        for path, expected in ((chrome, bundle.chrome_sha256), (driver, bundle.driver_sha256)):
            if expected and _sha256(path).lower() != expected.lower():
                raise BrowserBundleError(f"브라우저 파일 검증 실패: {path.name}")
    return bundle


def writable_driver_copy(bundle: BrowserBundle) -> Path:
    base = data_root() / "driver" / bundle.version
    base.mkdir(parents=True, exist_ok=True)
    # UC modifies the executable. Never replace a file another browser/process
    # may already be using, even when all programs share the same install folder.
    target_dir = Path(tempfile.mkdtemp(prefix="session-", dir=base))
    target = target_dir / "chromedriver.exe"
    try:
        shutil.copy2(bundle.driver, target)
    except Exception:
        _remove_driver_copy(target)
        raise
    return target


def _remove_driver_copy(path: Path) -> None:
    # Only our exact file and then its empty directory. No recursive deletion,
    # process killing, or cleanup of another session's resources.
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        pass  # Windows can retain an executable handle briefly after quit.


class _OwnedBrowser:
    def __init__(self, browser, driver_copy: Path):
        self._browser = browser
        self._driver_copy = driver_copy
        self._quit = browser.quit
        self._quit_lock = Lock()
        self._closed = False
        # UC.__del__ calls self.quit() again. Guard that path as well as the
        # application's close, rather than running shutdown twice on Windows.
        browser.quit = self.quit

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def quit(self):
        with self._quit_lock:
            if self._closed:
                _remove_driver_copy(self._driver_copy)
                return
            self._closed = True
        try:
            return self._quit()
        finally:
            _remove_driver_copy(self._driver_copy)


def create_browser(status_callback=None, *, headless: bool = False, diagnostic_logging: bool = False):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    import undetected_chromedriver as uc

    bundle = load_browser_bundle()
    driver = writable_driver_copy(bundle)
    args = [
        "--window-size=1024,768",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
    ]
    if headless:
        args.append("--headless=new")
    options = uc.ChromeOptions()
    options.binary_location = str(bundle.chrome)
    if diagnostic_logging:
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL', 'browser': 'ALL'})
    for arg in args:
        options.add_argument(arg)
    try:
        browser = uc.Chrome(options=options, driver_executable_path=str(driver),
                            browser_executable_path=str(bundle.chrome), use_subprocess=True,
                            version_main=int(bundle.version.split('.')[0]))
        return _OwnedBrowser(browser, driver), False
    except Exception as uc_error:
        if status_callback:
            status_callback("UC 시작 실패: 동일 고정 버전 표준 드라이버로 1회 재시도합니다. 탐지 회피 수준이 낮아집니다.")
        standard_options = Options()
        standard_options.binary_location = str(bundle.chrome)
        if diagnostic_logging:
            standard_options.set_capability('goog:loggingPrefs', {'performance': 'ALL', 'browser': 'ALL'})
        for arg in args:
            standard_options.add_argument(arg)
        try:
            browser = webdriver.Chrome(service=Service(str(bundle.driver)), options=standard_options)
            return _OwnedBrowser(browser, driver), True
        except Exception as standard_error:
            _remove_driver_copy(driver)
            raise BrowserBundleError(f"앱 전용 브라우저 시작 실패: {standard_error}") from uc_error
