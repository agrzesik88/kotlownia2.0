from pathlib import Path

from controller.events import ControllerEvent, EventType
from controller.history import HistoryRepository
from controller.state import ControllerState


def test_history_records_and_reads_latest_state(tmp_path: Path) -> None:
    history = HistoryRepository(tmp_path / "history.db")
    state = ControllerState(
        pipe_temperature_c=51.5,
        pellet_level_percent=42.0,
        automation_state="BOILER_LOADING",
        updated_at="2026-07-24T12:00:00+00:00",
    )
    try:
        history.record_state(state)
        latest = history.latest_measurement()
    finally:
        history.close()

    assert latest is not None
    assert latest["pipe_temperature_c"] == 51.5
    assert latest["automation_state"] == "BOILER_LOADING"


def test_history_records_events(tmp_path: Path) -> None:
    history = HistoryRepository(tmp_path / "history.db")
    try:
        history.record_event(
            ControllerEvent(
                EventType.PELLET_LOW,
                "niski pellet",
                {"pellet_level_percent": 10.0},
            )
        )
        count = history.count_events(EventType.PELLET_LOW.value)
    finally:
        history.close()

    assert count == 1
