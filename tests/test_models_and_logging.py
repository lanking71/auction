from datetime import datetime

import pytest

from bid_logging import mask_account, sanitize_message
from bid_models import BidTaskSpec


def test_task_specs_keep_price_and_time_associated():
    first = BidTaskSpec("https://itempage3.auction.co.kr/a", 100, datetime(2026, 1, 1), "first")
    second = BidTaskSpec("https://itempage3.auction.co.kr/b", 200, datetime(2026, 1, 2), "second")
    assert [(x.price, x.target_server_time.day) for x in (first, second)] == [(100, 1), (200, 2)]


def test_manual_offset_validation():
    with pytest.raises(ValueError):
        BidTaskSpec("https://itempage3.auction.co.kr/a", 1, datetime.now(), "id", 501)


def test_secrets_are_masked():
    assert mask_account("abcdef") == "ab****"
    assert "secret" not in sanitize_message("password=secret cookie:token")
