"""Conservative reconciliation of a submission with server history.

Masked account identity alone is never evidence that this attempt was accepted.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import re


@dataclass(frozen=True)
class BidRecord:
    account: str
    registered_at: datetime
    price: int
    raw: str
    precision_ms: float


def parse_record(cells: list[str]) -> BidRecord | None:
    raw = " | ".join(cells)
    stamp = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", raw)
    if not stamp or not cells:
        return None
    value = stamp.group(0)
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in value else "%Y-%m-%d %H:%M:%S"
    prices = [re.search(r"(?<!\d)([\d,]+)\s*원", c) for c in cells]
    price = next((int(m.group(1).replace(",", "")) for m in prices if m), None)
    if price is None:
        return None
    precision = 1000.0 if "." not in value else 1000 * 10 ** -len(value.split(".")[1])
    return BidRecord(cells[0].strip(), datetime.strptime(value, fmt), price, raw, precision)


def reconcile(before: list[BidRecord], after: list[BidRecord], *, account_id: str,
              price: int, clicked: datetime | None, returned: datetime,
              server_offset_ms: float = 0, server_uncertainty_ms: float | None = None) -> dict:
    rank = next((i + 1 for i, r in enumerate(after) if r.account == account_id), None)
    result = {"accepted": None, "rank": rank, "record": None,
              "evidence": "history_not_uniquely_attributed"}
    if clicked is None or server_uncertainty_ms is None:
        return result
    counts = Counter(r.raw for r in before)
    new = []
    for row in after:
        if counts[row.raw]:
            counts[row.raw] -= 1
        else:
            new.append(row)
    lower = clicked + timedelta(milliseconds=server_offset_ms - server_uncertainty_ms)
    upper = returned + timedelta(milliseconds=server_offset_ms + server_uncertainty_ms)
    matches = [r for r in new if r.account == account_id and "*" not in r.account
               and r.price == price and lower <= r.registered_at <= upper]
    if len(matches) == 1:
        result.update(accepted=True, record=matches[0], evidence="new_exact_account_price_time")
    return result
