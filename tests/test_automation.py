import pytest

from controller.automation import AutomationController, AutomationInput, BoilerState


def make_input(
    pipe_temperature_c: float = 20.0,
    pellet_level_percent: float = 75.0,
    pellet_heating_detected: bool = False,
    monotonic_seconds: float = 0.0,
    electric_heater_requested: bool = False,
) -> AutomationInput:
    return AutomationInput(
        pipe_temperature_c=pipe_temperature_c,
        pellet_level_percent=pellet_level_percent,
        pellet_heating_detected=pellet_heating_detected,
        monotonic_seconds=monotonic_seconds,
        electric_heater_requested=electric_heater_requested,
    )


def test_boot_goes_to_idle() -> None:
    controller = AutomationController()
    decision = controller.evaluate(make_input())
    assert decision.state is BoilerState.IDLE
    assert not decision.boiler_loading_on
    assert not decision.electric_heater_on


def test_rejects_invalid_sensor_values() -> None:
    controller = AutomationController()
    with pytest.raises(ValueError, match="Temperatura"):
        controller.evaluate(make_input(pipe_temperature_c=200.0))
    with pytest.raises(ValueError, match="Poziom pelletu"):
        controller.evaluate(make_input(pellet_level_percent=120.0))


def test_loading_starts_at_45_degrees() -> None:
    controller = AutomationController(boiler_loading_temperature_c=45.0)
    decision = controller.evaluate(
        make_input(
            pipe_temperature_c=45.0,
            pellet_heating_detected=True,
            monotonic_seconds=100.0,
        )
    )
    assert decision.state is BoilerState.BOILER_LOADING
    assert decision.boiler_loading_on
    assert not decision.electric_heater_on


def test_loading_runs_for_configured_ten_minutes() -> None:
    controller = AutomationController(boiler_loading_seconds=600.0)
    controller.evaluate(
        make_input(
            pipe_temperature_c=50.0,
            pellet_heating_detected=True,
            monotonic_seconds=100.0,
        )
    )
    before = controller.evaluate(
        make_input(
            pipe_temperature_c=50.0,
            pellet_heating_detected=True,
            monotonic_seconds=699.9,
        )
    )
    after = controller.evaluate(
        make_input(
            pipe_temperature_c=50.0,
            pellet_heating_detected=True,
            monotonic_seconds=700.0,
        )
    )
    assert before.boiler_loading_on
    assert not after.boiler_loading_on
    assert after.state is BoilerState.PELLET_HEATING


def test_loading_is_not_restarted_before_hourly_recheck() -> None:
    controller = AutomationController(
        boiler_loading_seconds=600.0,
        boiler_loading_recheck_seconds=3600.0,
    )
    controller.evaluate(
        make_input(pipe_temperature_c=50, pellet_heating_detected=True, monotonic_seconds=100)
    )
    controller.evaluate(
        make_input(pipe_temperature_c=50, pellet_heating_detected=True, monotonic_seconds=700)
    )
    during_pause = controller.evaluate(
        make_input(pipe_temperature_c=60, pellet_heating_detected=True, monotonic_seconds=4299.9)
    )
    rechecked = controller.evaluate(
        make_input(pipe_temperature_c=60, pellet_heating_detected=True, monotonic_seconds=4300)
    )
    assert not during_pause.boiler_loading_on
    assert rechecked.boiler_loading_on
    assert rechecked.state is BoilerState.BOILER_LOADING


def test_recheck_does_not_load_when_temperature_is_below_threshold() -> None:
    controller = AutomationController(
        boiler_loading_seconds=600.0,
        boiler_loading_recheck_seconds=3600.0,
    )
    controller.evaluate(
        make_input(pipe_temperature_c=50, pellet_heating_detected=True, monotonic_seconds=100)
    )
    controller.evaluate(
        make_input(pipe_temperature_c=50, pellet_heating_detected=True, monotonic_seconds=700)
    )
    decision = controller.evaluate(
        make_input(pipe_temperature_c=44.9, pellet_heating_detected=False, monotonic_seconds=4300)
    )
    assert not decision.boiler_loading_on
    assert decision.state is BoilerState.IDLE


def test_heater_never_runs_together_with_loading_pump() -> None:
    controller = AutomationController()
    decision = controller.evaluate(
        make_input(
            pipe_temperature_c=50,
            pellet_heating_detected=True,
            monotonic_seconds=100,
            electric_heater_requested=True,
        )
    )
    assert decision.boiler_loading_on
    assert not decision.electric_heater_on


def test_heater_can_start_after_loading_finishes() -> None:
    controller = AutomationController(boiler_loading_seconds=600.0)
    controller.evaluate(
        make_input(pipe_temperature_c=50, pellet_heating_detected=True, monotonic_seconds=100)
    )
    decision = controller.evaluate(
        make_input(
            pipe_temperature_c=50,
            pellet_heating_detected=True,
            monotonic_seconds=700,
            electric_heater_requested=True,
        )
    )
    assert not decision.boiler_loading_on
    assert decision.electric_heater_on
    assert decision.state is BoilerState.ELECTRIC_HEATING


def test_low_pellet_flag_uses_configured_threshold() -> None:
    controller = AutomationController(pellet_low_level_percent=15.0)
    decision = controller.evaluate(make_input(pellet_level_percent=15.0))
    assert decision.pellet_low


def test_monotonic_time_cannot_go_backwards() -> None:
    controller = AutomationController()
    controller.evaluate(make_input(monotonic_seconds=10.0))
    with pytest.raises(ValueError, match="cofać"):
        controller.evaluate(make_input(monotonic_seconds=9.0))


def test_fail_safe_turns_heater_and_loading_off() -> None:
    controller = AutomationController()
    decision = controller.fail_safe("awaria czujnika")
    assert decision.state is BoilerState.ERROR
    assert not decision.boiler_loading_on
    assert not decision.electric_heater_on
    assert decision.pellet_boiler_power_on


def test_cwu_schedule_request_is_forwarded_to_decision() -> None:
    controller = AutomationController()
    decision = controller.evaluate(
        AutomationInput(
            pipe_temperature_c=20.0,
            pellet_level_percent=75.0,
            pellet_heating_detected=False,
            monotonic_seconds=1.0,
            cwu_circulation_requested=True,
        )
    )
    assert decision.cwu_circulation_on is True


def test_manual_boiler_loading_has_priority_over_heater() -> None:
    controller = AutomationController()
    decision = controller.evaluate(
        AutomationInput(
            pipe_temperature_c=20.0,
            pellet_level_percent=75.0,
            pellet_heating_detected=False,
            monotonic_seconds=1.0,
            electric_heater_requested=True,
            boiler_loading_requested=True,
        )
    )
    assert decision.boiler_loading_on is True
    assert decision.electric_heater_on is False


def test_pellet_boiler_power_can_be_overridden_off() -> None:
    controller = AutomationController()
    decision = controller.evaluate(
        AutomationInput(
            pipe_temperature_c=20.0,
            pellet_level_percent=75.0,
            pellet_heating_detected=False,
            monotonic_seconds=1.0,
            pellet_boiler_power_override=False,
        )
    )
    assert decision.pellet_boiler_power_on is False
