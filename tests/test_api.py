import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app


def write_config(tmp_path: Path) -> Path:
    source = Path("config/settings.toml").read_text(encoding="utf-8")
    source = source.replace(
        'state_file = "runtime/state.json"',
        f'state_file = "{tmp_path / "state.json"}"',
    )
    source = source.replace(
        'schedule_file = "runtime/schedule.json"',
        f'schedule_file = "{tmp_path / "schedule.json"}"',
    )
    source = source.replace(
        'database_file = "runtime/history.db"',
        f'database_file = "{tmp_path / "history.db"}"',
    )
    path = tmp_path / "settings.toml"
    path.write_text(source, encoding="utf-8")
    return path


def test_status_reads_atomic_state_file(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    (tmp_path / "state.json").write_text(
        json.dumps({"automation_state": "IDLE", "pipe_temperature_c": 21.5}),
        encoding="utf-8",
    )
    client = TestClient(create_app(config))
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["automation_state"] == "IDLE"


def test_schedule_can_be_saved_and_read(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    payload = {
        "timezone": "Europe/Warsaw",
        "cwu_circulation": {
            "enabled": True,
            "windows": [{"start": "06:00", "end": "06:10", "weekdays": ["mon"]}],
        },
        "electric_heater": {"enabled": False, "windows": []},
    }
    response = client.put("/api/schedule", json=payload)
    assert response.status_code == 200
    assert client.get("/api/schedule").json() == payload


def test_schedule_rejects_invalid_time(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    payload = {
        "timezone": "Europe/Warsaw",
        "cwu_circulation": {
            "enabled": True,
            "windows": [{"start": "99:00", "end": "06:10", "weekdays": ["mon"]}],
        },
        "electric_heater": {"enabled": False, "windows": []},
    }
    assert client.put("/api/schedule", json=payload).status_code == 422
