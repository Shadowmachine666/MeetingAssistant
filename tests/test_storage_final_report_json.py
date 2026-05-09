import json
from pathlib import Path

from infrastructure.storage.storage_service import StorageService


def test_save_final_report_json_writes_file(tmp_path: Path):
    storage = StorageService(
        recordings_path=str(tmp_path / "Recordings"),
        reports_path=str(tmp_path / "Reports"),
        templates_path=str(tmp_path / "Templates"),
        logs_path=str(tmp_path / "Logs"),
    )
    payload = {"a": 1, "b": "x"}
    out_path = storage.save_final_report_json("meeting1234", payload)
    p = Path(out_path)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == payload

