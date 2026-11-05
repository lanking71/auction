from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from precision_scheduler import wait_until_ns


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure local perf_counter_ns scheduler firing error")
    parser.add_argument("--runs", type=int, default=1000)
    parser.add_argument("--lead-ms", type=float, default=5.0)
    args = parser.parse_args()
    errors = []
    for _ in range(args.runs):
        deadline = time.perf_counter_ns() + int(args.lead_ms * 1_000_000)
        wait_until_ns(deadline)
        errors.append((time.perf_counter_ns() - deadline) / 1_000_000)
    print(f"runs={len(errors)}")
    print(f"p50_ms={statistics.median(errors):.6f}")
    print(f"p95_ms={percentile(errors, 0.95):.6f}")
    print(f"p99_ms={percentile(errors, 0.99):.6f}")
    print(f"max_ms={max(errors):.6f}")
    if percentile(errors, 0.95) > 1.0:
        print("WARNING: p95 scheduler firing error exceeds 1 ms")


if __name__ == "__main__":
    main()
