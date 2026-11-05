from __future__ import annotations

import json
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app_paths import data_path


class LatencyHistory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_path("latency_history.json")
        self._lock = threading.Lock()

    @staticmethod
    def automatic_offset(values: Iterable[float]) -> float:
        valid = [float(v) for v in values if 0.0 <= float(v) <= 2000.0]
        return float(statistics.median(valid[-5:])) if valid else 0.0

    def _read(self) -> list[dict]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def values(self) -> list[float]:
        return [x["latency_ms"] for x in self._read() if isinstance(x, dict) and "latency_ms" in x]

    def current_ms(self) -> float:
        return self.automatic_offset(self.values())

    def record(self, latency_ms: float, *, success: bool) -> bool:
        if not success or not 0.0 <= latency_ms <= 2000.0:
            return False
        with self._lock:
            rows = self._read()
            rows.append({
                "latency_ms": round(float(latency_ms), 3),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            rows = rows[-20:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        return True
