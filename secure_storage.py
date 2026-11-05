from __future__ import annotations

import ctypes
import json
import os
import pickle
from ctypes import wintypes
from pathlib import Path
from typing import Any

import keyring

from app_paths import bundle_root, data_path


SERVICE_NAME = "Aucton"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(value: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(value)
    return _DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _crypt(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI cookie storage is only supported on Windows")
    source, source_buffer = _blob(data)
    result = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = func(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    else:
        ok = func(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def save_password(account_id: str, password: str) -> None:
    keyring.set_password(SERVICE_NAME, account_id, password)


def get_password(account_id: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, account_id)


def delete_password(account_id: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, account_id)
    except keyring.errors.PasswordDeleteError:
        pass


def save_cookies(cookies: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or data_path("cookies.dpapi")
    payload = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
    encrypted = _crypt(payload, True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_bytes(encrypted)
    temp.replace(target)


def load_cookies(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or data_path("cookies.dpapi")
    try:
        value = json.loads(_crypt(target.read_bytes(), False).decode("utf-8"))
        return value if isinstance(value, list) else []
    except FileNotFoundError:
        return []


def save_config(config: dict[str, Any]) -> None:
    safe = {k: v for k, v in config.items() if k.lower() not in {"password", "pw", "cookies", "cookie"}}
    target = data_path("config.json")
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def migrate_legacy_files() -> list[str]:
    """Migrate only after secure writes succeed; never delete on partial failure."""
    migrated: list[str] = []
    account_file = bundle_root() / "account_data.json"
    if account_file.exists() and account_file.resolve() != data_path("account_data.json").resolve():
        rows = json.loads(account_file.read_text(encoding="utf-8"))
        clean = []
        for row in rows if isinstance(rows, list) else []:
            account_id = str(row.get("id", "")).strip()
            if account_id and row.get("pw"):
                save_password(account_id, str(row["pw"]))
            if account_id:
                clean.append({"id": account_id})
        target = data_path("account_data.json")
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(target)
        account_file.write_text("[]\n", encoding="utf-8")
        migrated.append("accounts")
    cookie_file = bundle_root() / "auction_cookies.pkl"
    if cookie_file.exists():
        with cookie_file.open("rb") as stream:
            cookies = pickle.load(stream)
        if not isinstance(cookies, list):
            raise ValueError("legacy cookie file has an invalid format")
        save_cookies(cookies)
        cookie_file.unlink()
        migrated.append("cookies")
    return migrated
