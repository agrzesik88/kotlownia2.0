import logging

import pytest

from controller.config import load_config
from controller.relays import RelayController


def test_simulated_relays_return_to_safe_state() -> None:
    config = load_config()
    relays = RelayController(config.relays, simulation=True)

    relays.set_cwu_circulation(True)
    relays.set_boiler_loading(True)
    relays.all_safe()

    assert relays.state.cwu_circulation_on is False
    assert relays.state.boiler_loading_on is False
    assert relays.state.electric_heater_on is False
    assert relays.state.pellet_boiler_power_on is True


def test_repeated_apply_does_not_repeat_relay_operations(caplog: pytest.LogCaptureFixture) -> None:
    config = load_config()
    caplog.set_level(logging.INFO, logger="controller.relays")
    relays = RelayController(config.relays, simulation=True)

    caplog.clear()
    changed_first = relays.apply(
        cwu_circulation_on=True,
        boiler_loading_on=False,
        electric_heater_on=False,
        pellet_boiler_power_on=True,
    )
    changed_second = relays.apply(
        cwu_circulation_on=True,
        boiler_loading_on=False,
        electric_heater_on=False,
        pellet_boiler_power_on=True,
    )

    messages = [record.getMessage() for record in caplog.records]
    assert changed_first is True
    assert changed_second is False
    assert messages == ["[SYMULACJA] Pompa cyrkulacyjna CWU -> WŁĄCZONE"]


def test_close_is_idempotent() -> None:
    config = load_config()
    relays = RelayController(config.relays, simulation=True)

    relays.close()
    relays.close()


def test_set_after_close_is_rejected() -> None:
    config = load_config()
    relays = RelayController(config.relays, simulation=True)
    relays.close()

    with pytest.raises(RuntimeError, match="już zamknięty"):
        relays.set_cwu_circulation(True)


def test_loading_pump_and_heater_interlock_is_preserved() -> None:
    config = load_config()
    relays = RelayController(config.relays, simulation=True)

    with pytest.raises(ValueError, match="nie mogą pracować równocześnie"):
        relays.apply(
            cwu_circulation_on=False,
            boiler_loading_on=True,
            electric_heater_on=True,
            pellet_boiler_power_on=True,
        )
