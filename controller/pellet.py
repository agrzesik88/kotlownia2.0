from __future__ import annotations

import time
import warnings
from statistics import median
from typing import Protocol

from controller.config import PelletConfig
from controller.errors import (
    InvalidMeasurementError,
    SensorError,
    SensorTimeoutError,
)


class DistanceSensorProtocol(Protocol):
    @property
    def distance(self) -> float:
        ...

    def close(self) -> None:
        ...


class PelletSensor:
    def __init__(
        self,
        config: PelletConfig,
        simulation: bool,
        *,
        sensor: DistanceSensorProtocol | None = None,
    ) -> None:
        self.config = config
        self.simulation = simulation
        self._sensor: DistanceSensorProtocol | None = sensor
        self._last_good_level_percent: float | None = None
        self._consecutive_failures = 0
        self._using_last_good_value = False

        self._validate_config()

        if not simulation and self._sensor is None:
            self._initialize_gpio()

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def using_last_good_value(self) -> bool:
        return self._using_last_good_value

    @property
    def last_good_level_percent(self) -> float | None:
        return self._last_good_level_percent

    def _validate_config(self) -> None:
        if self.config.empty_distance_cm <= self.config.full_distance_cm:
            raise InvalidMeasurementError(
                "pellet.empty_distance_cm musi być większe "
                "od pellet.full_distance_cm"
            )

        if self.config.sample_count < 1:
            raise InvalidMeasurementError(
                "pellet.sample_count musi być większe lub równe 1"
            )

        if not 1 <= self.config.minimum_valid_samples <= self.config.sample_count:
            raise InvalidMeasurementError(
                "pellet.minimum_valid_samples musi mieścić się w zakresie "
                "od 1 do pellet.sample_count"
            )

        if self.config.max_consecutive_failures < 1:
            raise InvalidMeasurementError(
                "pellet.max_consecutive_failures musi być większe lub równe 1"
            )

        if self.config.sample_interval_seconds < 0:
            raise InvalidMeasurementError(
                "pellet.sample_interval_seconds nie może być ujemne"
            )

        if self.config.level_tolerance_percent < 0:
            raise InvalidMeasurementError(
                "pellet.level_tolerance_percent nie może być ujemne"
            )

    def _initialize_gpio(self) -> None:
        try:
            from gpiozero import DistanceSensor
            from gpiozero.exc import DistanceSensorNoEcho, PWMSoftwareFallback
        except ImportError as exc:
            raise SensorError(
                "Brak gpiozero. Zainstaluj zależności sprzętowe "
                "przed wyłączeniem symulacji pelletu."
            ) from exc

        # gpiozero performs echo monitoring in a background thread, so a local
        # catch_warnings() around ``sensor.distance`` cannot intercept these
        # warnings reliably. The controller has its own failure counters and
        # stale-value diagnostics, therefore these low-level warnings would only
        # duplicate information and flood journald.
        warnings.filterwarnings("ignore", category=DistanceSensorNoEcho)
        warnings.filterwarnings("ignore", category=PWMSoftwareFallback)

        try:
            self._sensor = DistanceSensor(
                echo=self.config.echo_gpio,
                trigger=self.config.trigger_gpio,
                max_distance=max(
                    self.config.empty_distance_cm / 100.0,
                    1.0,
                ),
            )
        except Exception as exc:
            raise SensorError(
                "Nie udało się zainicjalizować czujnika HC-SR04"
            ) from exc

    def read_level_percent(self) -> float:
        if self.simulation:
            value = self._clamp(self.config.simulation_level_percent)
            self._mark_success(value)
            return value

        try:
            distance_cm = self.read_distance_cm()
            level_percent = self.distance_to_percent(distance_cm)
        except (SensorError, SensorTimeoutError, InvalidMeasurementError) as exc:
            return self._handle_failed_read(exc)

        if (
            self._last_good_level_percent is not None
            and abs(level_percent - self._last_good_level_percent)
            <= self.config.level_tolerance_percent
        ):
            level_percent = self._last_good_level_percent

        self._mark_success(level_percent)
        return level_percent

    def _mark_success(self, level_percent: float) -> None:
        self._last_good_level_percent = level_percent
        self._consecutive_failures = 0
        self._using_last_good_value = False

    def _handle_failed_read(self, exc: Exception) -> float:
        self._consecutive_failures += 1
        self._using_last_good_value = self._last_good_level_percent is not None

        if (
            self._last_good_level_percent is not None
            and self._consecutive_failures < self.config.max_consecutive_failures
        ):
            return self._last_good_level_percent

        raise SensorTimeoutError(
            "HC-SR04 nie dostarczył poprawnego pomiaru przez "
            f"{self._consecutive_failures} kolejnych cykli"
        ) from exc

    def read_distance_cm(self) -> float:
        if self._sensor is None:
            raise SensorError("Czujnik pelletu nie został zainicjalizowany")

        measurements: list[float] = []
        maximum_distance_cm = max(
            self.config.empty_distance_cm * 1.5,
            self.config.empty_distance_cm + 20.0,
        )

        for index in range(self.config.sample_count):
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    distance_cm = float(self._sensor.distance) * 100.0

                no_echo = any(
                    warning.category.__name__ == "DistanceSensorNoEcho"
                    for warning in caught
                )
                if no_echo:
                    continue

                if distance_cm <= 0 or distance_cm > maximum_distance_cm:
                    continue

                measurements.append(distance_cm)
            except Exception:
                # Pojedyncza nieudana próbka nie unieważnia całej serii.
                pass

            if index < self.config.sample_count - 1:
                time.sleep(self.config.sample_interval_seconds)

        if len(measurements) < self.config.minimum_valid_samples:
            raise SensorTimeoutError(
                "Za mało poprawnych próbek HC-SR04: "
                f"{len(measurements)}/{self.config.sample_count}"
            )

        return float(median(measurements))

    def distance_to_percent(self, distance_cm: float) -> float:
        empty = self.config.empty_distance_cm
        full = self.config.full_distance_cm

        percent = (empty - distance_cm) / (empty - full) * 100.0
        return self._clamp(percent)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, value))

    def close(self) -> None:
        if self._sensor is not None:
            try:
                self._sensor.close()
            finally:
                self._sensor = None
