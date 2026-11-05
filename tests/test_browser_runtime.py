import json
from pathlib import Path

import pytest

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
