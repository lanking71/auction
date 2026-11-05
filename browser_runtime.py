from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

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


def _binary_version(path: Path) -> str:
    try:
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True,
                                timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BrowserBundleError(f"버전 확인 실패: {path.name}: {exc}") from exc
    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout + result.stderr)
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
    target_dir = data_root() / "driver" / bundle.version
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "chromedriver.exe"
    if not target.exists() or _sha256(target) != _sha256(bundle.driver):
        fd, temp_name = tempfile.mkstemp(prefix="chromedriver-", suffix=".tmp", dir=target_dir)
        os.close(fd)
        temp = Path(temp_name)
        try:
            shutil.copy2(bundle.driver, temp)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    return target


def create_browser(status_callback=None):
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
    options = uc.ChromeOptions()
    options.binary_location = str(bundle.chrome)
    for arg in args:
        options.add_argument(arg)
    try:
        return uc.Chrome(options=options, driver_executable_path=str(driver),
                         browser_executable_path=str(bundle.chrome), use_subprocess=True), False
    except Exception as uc_error:
        if status_callback:
            status_callback("UC 시작 실패: 동일 고정 버전 표준 드라이버로 1회 재시도합니다. 탐지 회피 수준이 낮아집니다.")
        standard_options = Options()
        standard_options.binary_location = str(bundle.chrome)
        for arg in args:
            standard_options.add_argument(arg)
        try:
            return webdriver.Chrome(service=Service(str(bundle.driver)), options=standard_options), True
        except Exception as standard_error:
            raise BrowserBundleError(f"앱 전용 브라우저 시작 실패: {standard_error}") from uc_error
