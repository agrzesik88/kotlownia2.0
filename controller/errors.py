class ControllerError(Exception):
    """Bazowy wyjątek aplikacji Kotłownia 2.0."""


class ConfigurationError(ControllerError):
    """Niepoprawna lub niekompletna konfiguracja."""


class SensorError(ControllerError):
    """Bazowy błąd czujnika."""


class SensorNotFoundError(SensorError):
    """Nie znaleziono czujnika."""


class SensorTimeoutError(SensorError):
    """Czujnik nie odpowiedział w wymaganym czasie."""


class InvalidMeasurementError(SensorError):
    """Czujnik zwrócił niepoprawny pomiar."""


class RelayError(ControllerError):
    """Błąd obsługi przekaźnika."""
