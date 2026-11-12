"""Measure fixed-price clicks and loopback request arrival, never live bids.

One/two isolated headless browsers, idle/one busy CPU process. Results include
misses and clock uncertainty; browser timing is NOT live server accuracy.
"""
from __future__ import annotations
import argparse
import json
import multiprocessing as mp
from pathlib import Path
import statistics
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from precision_scheduler import arm_browser_timer, sample_browser_clock, timer_command
from scripts.mock_auction import local_browser, mock_server


def load_cpu(stop):
    value = 1
    while not stop.is_set():
        for _ in range(20000):
            value = (value * 1664525 + 1013904223) & 0xFFFFFFFF


def summary(values):
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    percentile = lambda q: ordered[min(len(ordered)-1, int((len(ordered)-1)*q))]
    return {"n": len(values), "p50": statistics.median(values), "p95": percentile(.95),
            "p99": percentile(.99), "max": max(values), "min": min(values)}


def scenario(url, server_rows, runs, workers, loaded, lead_ms):
    records, lock = [], threading.Lock()
    stop = mp.Event()
    load = mp.Process(target=load_cpu, args=(stop,)) if loaded else None
    if load:
        load.start()
    def worker(worker_id, count):
        browser = None
        try:
            browser = local_browser()
            browser.get(url)
            for i in range(count):
                key = f"{workers}-{loaded}-{worker_id}-{i}"
                record = {"id": key, "status": "unknown"}
                try:
                    # Resample before every attempt, exactly the production script.
                    bridge = sample_browser_clock(browser)
                    browser.execute_script("window.mockTask=arguments[0]", key)
                    deadline = time.perf_counter_ns() + round(lead_ms*1e6)
                    record.update(deadline_ns=deadline, clock_uncertainty_ms=bridge.uncertainty_ms)
                    ack = arm_browser_timer(browser, deadline, task_id=key, bridge=bridge)
                    if ack.get("state") != "armed":
                        record["status"] = ack.get("state", "unknown")
                    else:
                        timer_command(browser, key, "enable")
                        end = deadline + 2_000_000_000
                        receipt = {}
                        while time.perf_counter_ns() < end:
                            receipt = timer_command(browser, key)
                            if receipt.get("state") != "armed":
                                break
                            time.sleep(0.02)
                        record["status"] = receipt.get("state", "unknown")
                        if receipt.get("clicked") is not None:
                            record["local_firing_error_ms"] = (bridge.python_time(receipt["fired"]) - deadline)/1e6
                            record["instrumented_click_error_ms"] = receipt["clicked"] - receipt["target"]
                            record["spin_ms"] = receipt["clicked"] - receipt["callback"]
                except Exception as exc:
                    record["error"] = type(exc).__name__
                    # Diagnostic recovery does not retry a submission.
                    browser.get(url)
                with lock:
                    records.append(record)
        except Exception as exc:
            with lock:
                records.append({"status": "worker_failed", "error": type(exc).__name__})
        finally:
            if browser:
                browser.quit()
    threads = [threading.Thread(target=worker, args=(i, runs//workers + (i < runs % workers)))
               for i in range(workers)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        if load:
            stop.set()
            load.join(5)
            if load.is_alive():
                load.terminate()
                load.join()
    time.sleep(.2)  # Allow the final loopback request to arrive.
    for record in records:
        received = [r for r in server_rows if r["id"] == record.get("id")]
        record["requests"] = len(received)
        if received and "deadline_ns" in record:
            row = received[0]
            record["request_error_ms"] = (row["received_ns"] - record["deadline_ns"])/1e6
            if row["target_ms"] is not None:
                record["browser_click_error_ms"] = row["event_ms"] - row["target_ms"]
    stats = {}
    for metric in ("local_firing_error_ms", "browser_click_error_ms", "request_error_ms"):
        values = [r[metric] for r in records if metric in r]
        stats[metric] = {"signed": summary(values), "absolute": summary([abs(v) for v in values])}
    statuses = {s: sum(r["status"] == s for r in records) for s in {r["status"] for r in records}}
    click95 = stats["browser_click_error_ms"]["absolute"].get("p95")
    return {"workers": workers, "cpu_load_processes": int(loaded), "requested_runs": runs,
            "statuses": statuses, "statistics_ms": stats,
            "clock_uncertainty_ms": summary([r["clock_uncertainty_ms"] for r in records if "clock_uncertainty_ms" in r]),
            "duplicate_requests": sum(r["requests"] > 1 for r in records),
            "missing_requests": sum(r["requests"] == 0 for r in records),
            "click_p95_within_1ms": click95 is not None and click95 <= 1,
            "records": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1000, help="attempts per scenario")
    parser.add_argument("--lead-ms", type=float, default=40)
    parser.add_argument("--output", default="benchmark_browser.json")
    args = parser.parse_args()
    if args.runs < 1 or args.lead_ms < 10:
        parser.error("runs >= 1 and lead-ms >= 10 required")
    report = {"scope": "headless fixed pinned Chrome, loopback mock only; not live server timing",
              "lead_ms": args.lead_ms, "scenarios": []}
    with mock_server() as (url, rows):
        for workers, loaded in [(1, False), (2, False), (1, True), (2, True)]:
            result = scenario(url, rows, args.runs, workers, loaded, args.lead_ms)
            report["scenarios"].append(result)
            print(json.dumps({k:v for k,v in result.items() if k != "records"}, ensure_ascii=False), flush=True)
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
