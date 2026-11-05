from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app_paths import data_path


def mask_account(value: str) -> str:
    if len(value) <= 2:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 2)


def sanitize_message(value: str) -> str:
    value = re.sub(r"(?i)(password|passwd|pw|cookie)(\s*[:=]\s*)([^\s,;]+)", r"\1\2***", value)
    return value


class JsonlBidLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_path("bid_runs.jsonl")

    def write(self, event: dict[str, Any]) -> None:
        def default(value: Any):
            if isinstance(value, datetime):
                return value.isoformat(timespec="microseconds")
            if is_dataclass(value):
                return asdict(value)
            return str(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe = dict(event)
        if "account_id" in safe:
            safe["account_id"] = mask_account(str(safe["account_id"]))
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(safe, ensure_ascii=False, default=default) + "\n")
