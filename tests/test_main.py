from pathlib import Path

from controller.config import load_config
from controller.main import ControllerApplication


def test_one_simulation_cycle_writes_state(tmp_path: Path) -> None:
    config = load_config()
    object.__setattr__(config.application, "simulation", True)
    object.__setattr__(config.application, "state_file", tmp_path / "state.json")
    object.__setattr__(config.history, "database_file", tmp_path / "history.db")
    object.__setattr__(config.history, "sample_interval_seconds", 0.0)
    object.__setattr__(config.temperature, "simulation", True)
    object.__setattr__(config.pellet, "simulation", True)
    app = ControllerApplication(config)
    try:
        state = app.run_once()
    finally:
        app.close()

    assert state.pipe_temperature_c == 20.0
    assert state.pellet_level_percent == 75.0
    assert state.last_error is None
    assert (tmp_path / "state.json").is_file()


def test_run_stops_after_requested_cycle(tmp_path: Path) -> None:
    config = load_config()
    object.__setattr__(config.application, "simulation", True)
    object.__setattr__(config.application, "state_file", tmp_path / "state.json")
    object.__setattr__(config.history, "database_file", tmp_path / "history.db")
    object.__setattr__(config.history, "sample_interval_seconds", 0.0)
    object.__setattr__(config.application, "loop_interval_seconds", 0.0)
    object.__setattr__(config.temperature, "simulation", True)
    object.__setattr__(config.pellet, "simulation", True)
    app = ControllerApplication(config)

    original_run_once = app.run_once
    cycles = 0

    def run_once_and_stop():
        nonlocal cycles
        cycles += 1
        state = original_run_once()
        app.request_stop()
        return state

    app.run_once = run_once_and_stop  # type: ignore[method-assign]
    try:
        app.run()
    finally:
        app.close()

    assert cycles == 1
    assert (tmp_path / "state.json").is_file()


def test_simulation_cycle_writes_sqlite_history(tmp_path: Path) -> None:
    from controller.history import HistoryRepository

    config = load_config()
    object.__setattr__(config.application, "simulation", True)
    object.__setattr__(config.application, "state_file", tmp_path / "state.json")
    object.__setattr__(config.history, "database_file", tmp_path / "history.db")
    object.__setattr__(config.history, "sample_interval_seconds", 0.0)
    object.__setattr__(config.temperature, "simulation", True)
    object.__setattr__(config.pellet, "simulation", True)

    app = ControllerApplication(config)
    app.run_once()
    app.close()

    history = HistoryRepository(tmp_path / "history.db")
    try:
        assert history.count_measurements() == 1
    finally:
        history.close()
