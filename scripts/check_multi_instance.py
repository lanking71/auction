"""Three separate programs, each with its own UC browser and 3 local bids.

This checks driver/process isolation, not 1ms performance. Functional tests
allow 100ms timer lateness; production's default remains 5ms.
"""
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_runtime import create_browser, load_browser_bundle, _sha256
from precision_scheduler import sample_browser_clock, arm_browser_timer, timer_command
from scripts.mock_auction import mock_server


def run_program(args):
    index, url, barrier = args
    browser = None
    result = {"program": index, "pid": os.getpid(), "attempts": []}
    try:
        browser, degraded = create_browser(headless=True)
        browser.set_page_load_timeout(10)
        browser.set_script_timeout(5)
        result.update(driver_copy=str(browser._driver_copy), standard_fallback=degraded)
        browser.get(url)
        barrier.wait(timeout=45)
        for bid in range(3):
            task = f"program-{index}-bid-{bid}"
            price = (index + 1) * 1000 + bid
            browser.execute_script("window.mockTask=arguments[0]; document.querySelector('#ctrlPrice').value=arguments[1]", task, price)
            bridge = sample_browser_clock(browser)
            # The production batch reserves >=300ms even BEFORE clock sampling.
            # Give this isolated functional check ample time for arm/enable IPC.
            deadline = time.perf_counter_ns() + 1_500_000_000 + index * 50_000_000
            ack = arm_browser_timer(browser, deadline, task_id=task, bridge=bridge, late_limit_ms=100)
            if ack.get("state") != "armed":
                raise RuntimeError(f"arm failed: {ack.get('state')}")
            enabled = timer_command(browser, task, "enable")
            receipt = {}
            until = deadline + 3_000_000_000
            while time.perf_counter_ns() < until:
                receipt = timer_command(browser, task)
                if receipt.get("state") != "armed":
                    break
                time.sleep(.02)
            result["attempts"].append({"task_id": task, "price": price, "state": receipt.get("state"),
                "receipt": receipt, "enable_ack": enabled,
                "clock_uncertainty_ms": bridge.uncertainty_ms})
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if browser:
            browser.quit()
    return result


def run_full_program(args):
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    import Auction as auction_module
    index, url, barrier, target = args
    copies, fallbacks = [], []
    real_create = create_browser
    def headless_create(callback):
        browser, degraded = real_create(callback, headless=True)
        copies.append(str(browser._driver_copy))
        fallbacks.append(degraded)
        return browser, degraded
    auction_module.create_browser = headless_create
    auction = auction_module.Auction()
    auction.validate_url = lambda value: None
    auction.loginstart = lambda *args: True  # Local fixture has no accounts.
    auction.latency_history = SimpleNamespace(current_ms=lambda *args: 0)
    auction._report = lambda result: None  # No writes to live settings/logs.
    specs = [auction_module.BidTaskSpec(url, (index+1)*1000+bid,
             target+timedelta(milliseconds=index*100+bid*300), f"mock-{index}") for bid in range(3)]
    barrier.wait(timeout=45)
    auction.auctionStart(specs, [])
    return {"program": index, "pid": os.getpid(), "driver_copies": copies,
            "standard_fallbacks": fallbacks,
            "attempts": [{"task_id": r.task.task_id, "price": r.submitted_price,
                          "state": r.timing.get("browser_receipt", {}).get("state", r.status),
                          "result_status": r.status, "receipt": r.timing.get("browser_receipt"),
                          "error": r.error, "timing": r.timing} for r in auction.last_results]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="3 programs x 3 browsers through full Auction workflow")
    parser.add_argument("--lead-seconds", type=float, default=80, help="preparation time for full workflow")
    args = parser.parse_args()
    bundle = load_browser_bundle()
    original = _sha256(bundle.driver)
    with mock_server() as (url, rows), mp.Manager() as manager:
        barrier = manager.Barrier(3)
        with ProcessPoolExecutor(max_workers=3) as pool:
            if args.full:
                from datetime import datetime, timedelta
                target = datetime.now()+timedelta(seconds=args.lead_seconds)
                programs = list(pool.map(run_full_program, [(i, url, barrier, target) for i in range(3)]))
            else:
                programs = list(pool.map(run_program, [(i, url, barrier) for i in range(3)]))
        time.sleep(.2)
        ids = [row["id"] for row in rows]
        copies = [path for p in programs for path in p.get("driver_copies", [p.get("driver_copy")])]
        okay = (len(programs) == 3 and len(set(copies)) == (9 if args.full else 3)
                and len({p["pid"] for p in programs}) == 3
                and all(not p.get("error") and len(p["attempts"]) == 3
                        and all(a["state"] == "fired" for a in p["attempts"]) for p in programs)
                and len(rows) == 9 and len(set(ids)) == 9 and _sha256(bundle.driver) == original)
        scope = (f"3 processes x 3 browsers, 9 full Auction tasks; {args.lead_seconds}s preparation lead, production 5ms late limit"
                 if args.full else "3 processes x 1 browser x 3 local bids; 1500ms lead, 100ms functional late limit")
        report = {"passed": okay, "scope": scope,
                  "production_late_limit_ms": 5, "programs": programs, "requests": list(rows),
                  "bundle_driver_unchanged": _sha256(bundle.driver) == original}
        Path("multi_instance_full_check.json" if args.full else "multi_instance_check.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"passed": okay, "scope": scope,
                          "requests": len(rows), "programs": programs}, indent=2, default=str), flush=True)
        if not okay:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
