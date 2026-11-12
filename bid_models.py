from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Event
from typing import Any, Optional
from uuid import uuid4
import math


@dataclass(frozen=True)
class BidTaskSpec:
    url: str
    price: int
    target_server_time: datetime
    account_id: str
    manual_offset_ms: float = 0.0
    fixed_price: bool = True
    max_price: int = 0
    additional_amount: int = 0
    task_id: str = field(default_factory=lambda: uuid4().hex)
    # Positive offset means server wall time is ahead of the PC. None means
    # no verified server clock sample exists; automatic learning is disabled.
    server_offset_ms: float = 0.0
    server_uncertainty_ms: Optional[float] = None
    automatic_login: bool = False

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("price must be non-negative")
        if not -500.0 <= self.manual_offset_ms <= 500.0:
            raise ValueError("manual_offset_ms must be between -500 and 500")
        if self.max_price < 0 or self.additional_amount < 0:
            raise ValueError("price limits must be non-negative")
        if not math.isfinite(self.server_offset_ms):
            raise ValueError("server offset must be finite")
        if self.server_uncertainty_ms is not None and (
            not math.isfinite(self.server_uncertainty_ms) or self.server_uncertainty_ms < 0
        ):
            raise ValueError("server clock uncertainty must be non-negative")


@dataclass
class BidTaskRuntime:
    cancel_event: Event = field(default_factory=Event)
    login_event: Event = field(default_factory=Event)
    browser: Optional[Any] = None
    session: Optional[Any] = None
    stealth_degraded: bool = False
    ready_event: Event = field(default_factory=Event)
    armed_event: Event = field(default_factory=Event)
    state: str = "preparing"
    cleanup_errors: list[str] = field(default_factory=list)

    def close(self) -> None:
        if self.browser is not None:
            try:
                self.browser.quit()
            except Exception as exc:
                self.cleanup_errors.append(type(exc).__name__ + ": browser close failed")
            self.browser = None
        if self.session is not None:
            try:
                self.session.close()
            except Exception as exc:
                self.cleanup_errors.append(type(exc).__name__ + ": session close failed")
            self.session = None


@dataclass
class BidResult:
    task: BidTaskSpec
    scheduler_fired_at: Optional[datetime] = None
    browser_clicked_at: Optional[datetime] = None
    webdriver_returned_at: Optional[datetime] = None
    server_registered_at: Optional[datetime] = None
    automatic_offset_ms: float = 0.0
    applied_offset_ms: float = 0.0
    success: bool = False
    cancelled: bool = False
    error: Optional[str] = None
    status: str = "preparing"
    accepted: Optional[bool] = None
    current_rank: Optional[int] = None
    submitted_price: Optional[int] = None
    timing: dict = field(default_factory=dict)
    observations: list[dict] = field(default_factory=list)
    cleanup_errors: list[str] = field(default_factory=list)
