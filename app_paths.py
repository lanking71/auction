from __future__ import annotations

import sys
from pathlib import Path


APP_NAME = "Aucton"


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def data_root() -> Path:
    # Keep runtime settings beside the project during development and beside
    # the executable in a packaged release, as requested by the application owner.
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_path(name: str) -> Path:
    return data_root() / name
