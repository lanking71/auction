from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Event
from typing import Any, Optional


@dataclass(frozen=True)
class BidTaskSpec:
    url: str
    price: int
    target_server_time: datetime
    account_id: str
    manual_offset_ms: float = 0.0
    fixed_price: bool = True

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("price must be non-negative")
        if not -500.0 <= self.manual_offset_ms <= 500.0:
            raise ValueError("manual_offset_ms must be between -500 and 500")


@dataclass
class BidTaskRuntime:
    cancel_event: Event = field(default_factory=Event)
    login_event: Event = field(default_factory=Event)
    browser: Optional[Any] = None
    session: Optional[Any] = None
    stealth_degraded: bool = False

    def close(self) -> None:
        if self.browser is not None:
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = None
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
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
