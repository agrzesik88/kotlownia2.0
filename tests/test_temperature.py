from pathlib import Path

from controller.temperature import TemperatureSensor


def test_ds18b20_file_is_parsed(tmp_path: Path) -> None:
    sensor_file = tmp_path / "w1_slave"
    sensor_file.write_text(
        "aa bb cc YES\naa bb cc t=51250\n",
        encoding="ascii",
    )

    assert TemperatureSensor._read_ds18b20(sensor_file) == 51.25


def test_ds18b20_uses_last_good_value_after_temporary_failure(tmp_path: Path) -> None:
    sensor_file = tmp_path / "w1_slave"
    sensor_file.write_text(
        "aa bb cc YES\naa bb cc t=51250\n",
        encoding="ascii",
    )

    from controller.config import TemperatureConfig

    config = TemperatureConfig(
        simulation=False,
        heating_available_c=45.0,
        read_interval_seconds=10.0,
        max_consecutive_failures=5,
        sensor_file=sensor_file,
        simulation_value_c=20.0,
    )
    sensor = TemperatureSensor(config, simulation=False)

    assert sensor.read_celsius() == 51.25

    sensor_file.write_text("aa bb cc YES\n", encoding="ascii")

    assert sensor.read_celsius() == 51.25
    assert sensor.consecutive_failures == 1
    assert sensor.using_last_good_value is True


def test_ds18b20_fails_after_maximum_consecutive_failures(tmp_path: Path) -> None:
    sensor_file = tmp_path / "w1_slave"
    sensor_file.write_text(
        "aa bb cc YES\naa bb cc t=51250\n",
        encoding="ascii",
    )

    from controller.config import TemperatureConfig
    from controller.errors import SensorTimeoutError

    config = TemperatureConfig(
        simulation=False,
        heating_available_c=45.0,
        read_interval_seconds=10.0,
        max_consecutive_failures=3,
        sensor_file=sensor_file,
        simulation_value_c=20.0,
    )
    sensor = TemperatureSensor(config, simulation=False)

    assert sensor.read_celsius() == 51.25
    sensor_file.write_text("aa bb cc YES\n", encoding="ascii")

    assert sensor.read_celsius() == 51.25
    assert sensor.read_celsius() == 51.25

    try:
        sensor.read_celsius()
    except SensorTimeoutError as exc:
        assert "3 kolejnych cykli" in str(exc)
    else:
        raise AssertionError("Oczekiwano SensorTimeoutError")
