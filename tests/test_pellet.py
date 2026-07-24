from __future__ import annotations

from dataclasses import replace

import pytest

from controller.config import load_config
from controller.errors import SensorTimeoutError
from controller.pellet import PelletSensor


class SequenceDistanceSensor:
    def __init__(self, values: list[float | Exception]) -> None:
        self.values = iter(values)
        self.closed = False

    @property
    def distance(self) -> float:
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self) -> None:
        self.closed = True


def hardware_config(**changes: object):
    base = load_config().pellet
    return replace(base, sample_interval_seconds=0.0, **changes)


def test_distance_is_converted_to_level() -> None:
    config = load_config()
    sensor = PelletSensor(config.pellet, simulation=True)

    assert sensor.distance_to_percent(10.0) == 100.0
    assert sensor.distance_to_percent(100.0) == 0.0
    assert sensor.distance_to_percent(55.0) == 50.0


def test_single_bad_samples_do_not_invalidate_measurement_series() -> None:
    backend = SequenceDistanceSensor(
        [0.30, RuntimeError("no echo"), 0.31, RuntimeError("no echo"), 0.32]
    )
    sensor = PelletSensor(
        hardware_config(sample_count=5, minimum_valid_samples=3),
        simulation=False,
        sensor=backend,
    )

    level = sensor.read_level_percent()

    assert level == pytest.approx((100.0 - 31.0) / 90.0 * 100.0)
    assert sensor.consecutive_failures == 0
    assert sensor.using_last_good_value is False


def test_last_good_value_is_used_until_failure_threshold() -> None:
    backend = SequenceDistanceSensor(
        [0.30] * 5
        + [RuntimeError("no echo")] * 5 * 5
    )
    sensor = PelletSensor(
        hardware_config(
            sample_count=5,
            minimum_valid_samples=3,
            max_consecutive_failures=5,
        ),
        simulation=False,
        sensor=backend,
    )

    first_level = sensor.read_level_percent()

    for expected_failures in range(1, 5):
        assert sensor.read_level_percent() == first_level
        assert sensor.consecutive_failures == expected_failures
        assert sensor.using_last_good_value is True

    with pytest.raises(SensorTimeoutError, match="5 kolejnych cykli"):
        sensor.read_level_percent()

    assert sensor.consecutive_failures == 5


def test_successful_read_resets_failure_counter() -> None:
    backend = SequenceDistanceSensor(
        [0.30] * 5
        + [RuntimeError("no echo")] * 5
        + [0.31] * 5
    )
    sensor = PelletSensor(
        hardware_config(sample_count=5, minimum_valid_samples=3),
        simulation=False,
        sensor=backend,
    )

    sensor.read_level_percent()
    sensor.read_level_percent()
    recovered_level = sensor.read_level_percent()

    assert recovered_level == pytest.approx((100.0 - 31.0) / 90.0 * 100.0)
    assert sensor.consecutive_failures == 0
    assert sensor.using_last_good_value is False
