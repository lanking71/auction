from pathlib import Path

from latency import LatencyHistory


def test_recent_five_median_and_filtering():
    assert LatencyHistory.automatic_offset([-1, 1, 2, 3, 4, 5, 9999]) == 3.0


def test_history_keeps_twenty_valid_records(tmp_path: Path):
    history = LatencyHistory(tmp_path / "latency.json")
    assert not history.record(-1, success=True)
    assert not history.record(12, success=False)
    for value in range(25):
        assert history.record(value, success=True)
    assert history.values() == [float(x) for x in range(5, 25)]
    assert history.current_ms() == 22.0
