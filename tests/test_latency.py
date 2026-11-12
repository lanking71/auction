from pathlib import Path
import json

from latency import LatencyHistory


def test_recent_five_median_and_filtering():
    assert LatencyHistory.automatic_offset([-1, 1, 2, 3, 4, 5, 9999]) == 3.0


def test_history_keeps_twenty_valid_records(tmp_path: Path):
    history = LatencyHistory(tmp_path / "latency.json")
    assert not history.record(-1, success=True)
    assert not history.record(12, success=False)
    for value in range(25):
        assert history.record(value, success=True, task_id=str(value), verified=True,
                              uncertainty_ms=0.2, evidence="mock_exact_record")
    assert history.values() == [float(x) for x in range(5, 25)]
    assert history.current_ms() == 22.0


def test_modes_legacy_and_uncertain_samples_are_excluded(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps([{"latency_ms": 999}]), encoding="utf-8")
    history = LatencyHistory(path)
    assert history.current_ms() == 0
    assert not history.record(20, success=True)
    assert not history.record(-20, success=True, task_id="negative", verified=True,
                              uncertainty_ms=0.2, evidence="mock")
    assert not history.record(20, success=True, task_id="uncertain", verified=True,
                              uncertainty_ms=1.1, evidence="mock")
    assert history.record(400, success=True, mode="normal", task_id="normal", verified=True,
                          uncertainty_ms=0.2, evidence="mock")
    assert history.current_ms() == 0
    assert history.current_ms("normal") == 400
    assert not history.record(400, success=True, mode="normal", task_id="normal", verified=True,
                              uncertainty_ms=0.2, evidence="mock")
