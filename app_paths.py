from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Aucton"


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / APP_NAME if base else Path.home() / ".aucton"
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_path(name: str) -> Path:
    return data_root() / name
