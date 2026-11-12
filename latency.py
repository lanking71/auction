from __future__ import annotations

import json
import statistics
import threading
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app_paths import data_path


class LatencyHistory:
    _locks: dict[str, threading.Lock] = {}
    _registry_lock = threading.Lock()

    def __init__(self, path: Path | None = None) -> None:
        # Never import or overwrite measurements with unknown mode/basis.
        self.path = path or data_path("latency_history_v2.json")
        with self._registry_lock:
            self._lock = self._locks.setdefault(str(self.path.resolve()), threading.Lock())

    @staticmethod
    def automatic_offset(values: Iterable[float]) -> float:
        valid = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and 0.0 <= number <= 2000.0:
                valid.append(number)
        return float(statistics.median(valid[-5:])) if valid else 0.0

    def _read(self) -> list[dict]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def values(self, mode: str = "fixed") -> list[float]:
        return [x["latency_ms"] for x in self._read() if isinstance(x, dict)
                and x.get("schema") == 2 and x.get("mode") == mode
                and x.get("basis") == "browser_click_to_server"
                and x.get("verified") is True and "latency_ms" in x]

    def current_ms(self, mode: str = "fixed") -> float:
        return self.automatic_offset(self.values(mode))

    def record(self, latency_ms: float, *, success: bool, mode: str = "fixed",
               task_id: str = "", verified: bool = False,
               uncertainty_ms: float | None = None, evidence: str = "") -> bool:
        if (not success or not verified or not task_id or not evidence
            or mode not in {"fixed", "normal"} or uncertainty_ms is None
            or not math.isfinite(uncertainty_ms) or not 0 <= uncertainty_ms <= 1.0
            or not math.isfinite(latency_ms) or not 0.0 <= latency_ms <= 2000.0):
            return False
        with self._lock:
            rows = self._read()
            if any(isinstance(r, dict) and r.get("task_id") == task_id for r in rows):
                return False
            rows.append({
                "schema": 2, "mode": mode, "basis": "browser_click_to_server",
                "task_id": task_id, "verified": True,
                "uncertainty_ms": uncertainty_ms, "evidence": evidence,
                "latency_ms": round(float(latency_ms), 3),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            # Preserve the last 20 records of each mode independently.
            rows = [r for m in ("fixed", "normal") for r in
                    [x for x in rows if isinstance(x, dict) and x.get("mode") == m][-20:]]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        return True
