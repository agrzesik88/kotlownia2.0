from __future__ import annotations

from pathlib import Path

from controller.config import TemperatureConfig
from controller.errors import (
    InvalidMeasurementError,
    SensorNotFoundError,
)


class TemperatureSensor:
    def __init__(self, config: TemperatureConfig, simulation: bool) -> None:
        self.config = config
        self.simulation = simulation

    def read_celsius(self) -> float:
        if self.simulation:
            return self.config.simulation_value_c

        sensor_file = self.config.sensor_file or self._discover_sensor_file()
        return self._read_ds18b20(sensor_file)

    @staticmethod
    def _discover_sensor_file() -> Path:
        candidates = sorted(Path("/sys/bus/w1/devices").glob("28-*/w1_slave"))

        if not candidates:
            raise SensorNotFoundError(
                "Nie znaleziono czujnika DS18B20 w /sys/bus/w1/devices"
            )

        if len(candidates) > 1:
            raise SensorNotFoundError(
                "Znaleziono kilka DS18B20. "
                "Ustaw temperature.sensor_file w settings.toml"
            )

        return candidates[0]

    @staticmethod
    def _read_ds18b20(sensor_file: Path) -> float:
        try:
            lines = sensor_file.read_text(encoding="ascii").splitlines()
        except FileNotFoundError as exc:
            raise SensorNotFoundError(
                f"Nie znaleziono pliku czujnika DS18B20: {sensor_file}"
            ) from exc
        except OSError as exc:
            raise InvalidMeasurementError(
                f"Nie można odczytać DS18B20: {sensor_file}"
            ) from exc

        if len(lines) < 2:
            raise InvalidMeasurementError(
                f"Niepełne dane z DS18B20: {sensor_file}"
            )

        if not lines[0].strip().endswith("YES"):
            raise InvalidMeasurementError(
                f"Błędny odczyt CRC z DS18B20: {sensor_file}"
            )

        marker = "t="
        position = lines[1].find(marker)

        if position < 0:
            raise InvalidMeasurementError(
                f"Brak temperatury w danych DS18B20: {sensor_file}"
            )

        raw_value = lines[1][position + len(marker) :]

        try:
            temperature_c = int(raw_value) / 1000.0
        except ValueError as exc:
            raise InvalidMeasurementError(
                f"Niepoprawna temperatura DS18B20: {raw_value!r}"
            ) from exc

        if temperature_c == 85.0:
            raise InvalidMeasurementError(
                "DS18B20 zwrócił wartość startową 85°C"
            )

        if not -55.0 <= temperature_c <= 125.0:
            raise InvalidMeasurementError(
                f"Temperatura DS18B20 poza zakresem: {temperature_c}°C"
            )

        return temperature_c
