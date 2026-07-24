from controller.state import ControllerState


def test_default_state_is_safe() -> None:
    state = ControllerState()

    assert state.cwu_circulation_on is False
    assert state.boiler_loading_on is False
    assert state.electric_heater_on is False
    assert state.pellet_boiler_power_on is True
    assert state.simulation_mode is True


def test_state_can_be_serialized() -> None:
    state = ControllerState(pipe_temperature_c=51.5)
    state.update_timestamp()

    data = state.to_dict()

    assert data["pipe_temperature_c"] == 51.5
    assert data["pellet_boiler_power_on"] is True
    assert data["updated_at"] != ""
