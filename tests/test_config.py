from pathlib import Path

from controller.config import load_config


def test_config_is_loaded() -> None:
    config = load_config(Path("config/settings.toml"))

    assert config.application.simulation is False
    assert config.relays.cwu_circulation_gpio == 6
    assert config.temperature.heating_available_c == 45.0
    assert config.pellet.minimum_valid_samples == 5
    assert config.pellet.max_consecutive_failures == 5
