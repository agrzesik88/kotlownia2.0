from __future__ import annotations

from controller.application import ControllerApplication
from controller.state import ControllerState


def _alerts(state: ControllerState) -> list[dict[str, str]]:
    app = ControllerApplication.__new__(ControllerApplication)
    app.state = state
    app._update_alerts()
    return state.alerts


def test_low_pellet_creates_warning() -> None:
    state = ControllerState(pellet_low=True, pellet_level_percent=12.5)

    alerts = _alerts(state)

    assert alerts == [
        {
            "severity": "WARNING",
            "code": "PELLET_LOW",
            "message": "Niski poziom pelletu: 12.5%",
        }
    ]


def test_stale_pellet_sensor_creates_warning() -> None:
    state = ControllerState(
        pellet_sensor_stale=True,
        pellet_sensor_consecutive_failures=3,
    )

    alerts = _alerts(state)

    assert alerts[0]["code"] == "PELLET_SENSOR_STALE"
    assert "3 błędów" in alerts[0]["message"]


def test_controller_error_creates_error() -> None:
    state = ControllerState(last_error="Błąd czujnika temperatury")

    alerts = _alerts(state)

    assert alerts == [
        {
            "severity": "ERROR",
            "code": "CONTROLLER_ERROR",
            "message": "Błąd sterownika: Błąd czujnika temperatury",
        }
    ]


def test_multiple_alerts_are_reported_together() -> None:
    state = ControllerState(
        pellet_low=True,
        pellet_level_percent=10.0,
        pellet_sensor_stale=True,
        pellet_sensor_consecutive_failures=2,
    )

    alerts = _alerts(state)

    assert [alert["code"] for alert in alerts] == [
        "PELLET_LOW",
        "PELLET_SENSOR_STALE",
    ]
