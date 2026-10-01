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
        'command_file = "runtime/manual_control.json"',
        f'command_file = "{tmp_path / "manual_control.json"}"',
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



def test_automation_status_reads_output_reasons(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "automation_state": "BOILER_LOADING",
                "automation_reason": "Trwa czasowe ładowanie bojlera",
                "output_status": {
                    "cwu_circulation": {
                        "state": "OFF",
                        "mode": "AUTO",
                        "reason": "Brak żądania cyrkulacji",
                    },
                    "boiler_loading": {
                        "state": "ON",
                        "mode": "AUTO",
                        "reason": "Trwa czasowe ładowanie bojlera",
                    },
                    "electric_heater": {
                        "state": "OFF",
                        "mode": "AUTO",
                        "reason": "Żądanie zablokowane — pracuje pompa bojlera",
                    },
                    "pellet_boiler_power": {
                        "state": "ON",
                        "mode": "AUTO",
                        "reason": "Zasilanie sterowane automatycznie",
                    },
                },
                "updated_at": "2026-10-01T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config))
    response = client.get("/api/automation-status")
    assert response.status_code == 200
    data = response.json()
    assert data["automation_state"] == "BOILER_LOADING"
    assert data["outputs"]["boiler_loading"]["state"] == "ON"
    assert data["outputs"]["boiler_loading"]["reason"] == "Trwa czasowe ładowanie bojlera"
    assert data["outputs"]["electric_heater"]["reason"] == "Żądanie zablokowane — pracuje pompa bojlera"


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


def test_manual_control_can_be_activated_and_cleared(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    response = client.post(
        "/api/manual/activate",
        json={"output": "cwu_circulation", "duration_minutes": 10},
    )
    assert response.status_code == 200
    assert response.json()["cwu_circulation_until"] is not None

    status = client.get("/api/manual")
    assert status.status_code == 200
    assert status.json()["cwu_circulation_active"] is True

    cleared = client.post("/api/manual/clear")
    assert cleared.status_code == 200
    assert cleared.json()["cwu_circulation_until"] is None


def test_manual_control_supports_boiler_and_power(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    loading = client.post("/api/manual/activate", json={"output": "boiler_loading", "duration_minutes": 10})
    assert loading.status_code == 200
    power = client.post("/api/manual/activate", json={"output": "pellet_boiler_power_off", "duration_minutes": 15})
    assert power.status_code == 200
    status = client.get("/api/manual").json()
    assert status["boiler_loading_active"] is True
    assert status["pellet_boiler_power_override"] is False


def test_manual_control_rejects_unknown_output(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    response = client.post(
        "/api/manual/activate",
        json={"output": "unknown_output", "duration_minutes": 10},
    )
    assert response.status_code == 422


def test_automation_settings_can_be_saved_and_read(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    payload = {
        "boiler_loading_temperature_c": 50.5,
        "boiler_loading_minutes": 15,
        "boiler_loading_recheck_minutes": 120,
        "pellet_low_level_percent": 20.0,
    }
    response = client.put("/api/automation-settings", json=payload)
    assert response.status_code == 200
    assert response.json() == payload
    assert client.get("/api/automation-settings").json() == payload


def test_automation_settings_store_runtime_values_in_seconds(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    payload = {
        "boiler_loading_temperature_c": 50.0,
        "boiler_loading_minutes": 15,
        "boiler_loading_recheck_minutes": 120,
        "pellet_low_level_percent": 20.0,
    }

    response = client.put("/api/automation-settings", json=payload)

    assert response.status_code == 200
    stored = json.loads(
        (tmp_path / "automation_settings.json").read_text(encoding="utf-8")
    )
    assert stored["boiler_loading_seconds"] == 900
    assert stored["boiler_loading_recheck_seconds"] == 7200
    assert client.get("/api/automation-settings").json() == payload


def test_automation_settings_reject_invalid_values(tmp_path: Path) -> None:
    client = TestClient(create_app(write_config(tmp_path)))
    response = client.put(
        "/api/automation-settings",
        json={
            "boiler_loading_temperature_c": 200,
            "boiler_loading_minutes": 0,
            "boiler_loading_recheck_minutes": 60,
            "pellet_low_level_percent": 15,
        },
    )
    assert response.status_code == 422
