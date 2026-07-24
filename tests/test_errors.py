from controller.errors import (
    ConfigurationError,
    ControllerError,
    InvalidMeasurementError,
    RelayError,
    SensorError,
    SensorNotFoundError,
    SensorTimeoutError,
)


def test_error_hierarchy() -> None:
    assert issubclass(ConfigurationError, ControllerError)
    assert issubclass(SensorError, ControllerError)
    assert issubclass(SensorNotFoundError, SensorError)
    assert issubclass(SensorTimeoutError, SensorError)
    assert issubclass(InvalidMeasurementError, SensorError)
    assert issubclass(RelayError, ControllerError)
