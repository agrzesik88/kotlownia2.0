from pathlib import Path

from controller.temperature import TemperatureSensor


def test_ds18b20_file_is_parsed(tmp_path: Path) -> None:
    sensor_file = tmp_path / "w1_slave"
    sensor_file.write_text(
        "aa bb cc YES\naa bb cc t=51250\n",
        encoding="ascii",
    )

    assert TemperatureSensor._read_ds18b20(sensor_file) == 51.25
