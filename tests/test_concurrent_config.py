from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json


def save_in_process(pair):
    import secure_storage
    target, number = pair
    secure_storage.data_path = lambda name: Path(target)
    secure_storage.save_config({"worker": number, "value": "x" * 10000, "password": "discard"})


def test_separate_programs_can_save_without_shared_temp_collision(tmp_path):
    path = tmp_path / "config.json"
    with ProcessPoolExecutor(max_workers=3) as pool:
        list(pool.map(save_in_process, [(str(path), i) for i in range(18)]))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["worker"] in range(18)
    assert len(data["value"]) == 10000
    assert "password" not in data
    assert not list(tmp_path.glob("*.tmp"))
