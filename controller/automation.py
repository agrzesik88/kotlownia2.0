from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class BoilerState(Enum):
    BOOT = auto()
    IDLE = auto()
    PELLET_HEATING = auto()
    BOILER_LOADING = auto()
    ELECTRIC_HEATING = auto()
    ERROR = auto()


@dataclass(slots=True, frozen=True)
class AutomationInput:
    pipe_temperature_c: float
    pellet_level_percent: float
    pellet_heating_detected: bool
    monotonic_seconds: float
    electric_heater_requested: bool = False
    cwu_circulation_requested: bool = False
    boiler_loading_requested: bool = False
    pellet_boiler_power_override: bool | None = None


@dataclass(slots=True, frozen=True)
class AutomationDecision:
    state: BoilerState
    cwu_circulation_on: bool
    boiler_loading_on: bool
    electric_heater_on: bool
    pellet_boiler_power_on: bool
    pellet_low: bool
    reason: str


class AutomationController:
    """Deterministyczna maszyna stanów kotłowni, niezależna od GPIO i systemu."""

    def __init__(
        self,
        boiler_loading_temperature_c: float = 45.0,
        boiler_loading_seconds: float = 600.0,
        boiler_loading_recheck_seconds: float = 3600.0,
        pellet_low_level_percent: float = 15.0,
    ) -> None:
        self._state = BoilerState.BOOT
        self._boiler_loading_started_at: float | None = None
        self._next_boiler_loading_check_at: float = 0.0
        self._last_monotonic_seconds: float | None = None
        self.update_settings(
            boiler_loading_temperature_c=boiler_loading_temperature_c,
            boiler_loading_seconds=boiler_loading_seconds,
            boiler_loading_recheck_seconds=boiler_loading_recheck_seconds,
            pellet_low_level_percent=pellet_low_level_percent,
        )

    def update_settings(
        self,
        *,
        boiler_loading_temperature_c: float,
        boiler_loading_seconds: float,
        boiler_loading_recheck_seconds: float,
        pellet_low_level_percent: float,
    ) -> None:
        """Aktualizuje parametry automatyki bez resetowania jej bieżącego stanu."""
        if boiler_loading_seconds <= 0:
            raise ValueError("Czas ładowania bojlera musi być większy od zera")
        if boiler_loading_recheck_seconds <= 0:
            raise ValueError("Odstęp ponownego sprawdzenia musi być większy od zera")
        if not -55.0 <= boiler_loading_temperature_c <= 125.0:
            raise ValueError("Próg ładowania bojlera jest poza zakresem")
        if not 0.0 <= pellet_low_level_percent <= 100.0:
            raise ValueError("Próg niskiego poziomu pelletu jest poza zakresem")

        self._boiler_loading_temperature_c = boiler_loading_temperature_c
        self._boiler_loading_seconds = boiler_loading_seconds
        self._boiler_loading_recheck_seconds = boiler_loading_recheck_seconds
        self._pellet_low_level_percent = pellet_low_level_percent

    @property
    def state(self) -> BoilerState:
        return self._state

    def evaluate(self, inputs: AutomationInput) -> AutomationDecision:
        self._validate_input(inputs)

        if self._last_monotonic_seconds is not None:
            if inputs.monotonic_seconds < self._last_monotonic_seconds:
                raise ValueError("Czas monotoniczny nie może się cofać")
        self._last_monotonic_seconds = inputs.monotonic_seconds

        pellet_low = inputs.pellet_level_percent <= self._pellet_low_level_percent
        self._pellet_boiler_power_on = (
            True if inputs.pellet_boiler_power_override is None
            else inputs.pellet_boiler_power_override
        )

        if self._state is BoilerState.BOOT:
            self._state = BoilerState.IDLE

        if inputs.boiler_loading_requested:
            self._state = BoilerState.BOILER_LOADING
            self._boiler_loading_started_at = None
            return self._decision(
                pellet_low=pellet_low,
                cwu_circulation_on=inputs.cwu_circulation_requested,
                boiler_loading_on=True,
                reason="Pompa bojlera pracuje w trybie ręcznym",
            )

        if self._state is BoilerState.BOILER_LOADING and self._boiler_loading_started_at is None:
            self._state = BoilerState.IDLE

        if self._state is BoilerState.BOILER_LOADING:
            return self._evaluate_boiler_loading(inputs, pellet_low)

        loading_due = (
            inputs.pellet_heating_detected
            and inputs.pipe_temperature_c >= self._boiler_loading_temperature_c
            and inputs.monotonic_seconds >= self._next_boiler_loading_check_at
        )

        if loading_due:
            self._state = BoilerState.BOILER_LOADING
            self._boiler_loading_started_at = inputs.monotonic_seconds
            return self._decision(
                pellet_low=pellet_low,
                cwu_circulation_on=inputs.cwu_circulation_requested,
                boiler_loading_on=True,
                reason="Rozpoczęto czasowe ładowanie bojlera",
            )

        if inputs.electric_heater_requested:
            self._state = BoilerState.ELECTRIC_HEATING
            return self._decision(
                pellet_low=pellet_low,
                cwu_circulation_on=inputs.cwu_circulation_requested,
                electric_heater_on=True,
                reason="Grzałka elektryczna pracuje na żądanie",
            )

        if inputs.pellet_heating_detected:
            self._state = BoilerState.PELLET_HEATING
            reason = "Wykryto pracę pieca pelletowego"
            if inputs.monotonic_seconds < self._next_boiler_loading_check_at:
                reason = "Piec pracuje; oczekiwanie na kolejne sprawdzenie ładowania bojlera"
            return self._decision(
                pellet_low=pellet_low,
                cwu_circulation_on=inputs.cwu_circulation_requested,
                reason=reason,
            )

        self._state = BoilerState.IDLE
        return self._decision(
            pellet_low=pellet_low,
            cwu_circulation_on=inputs.cwu_circulation_requested,
            reason="Sterownik gotowy — oczekiwanie w stanie IDLE",
        )

    def fail_safe(self, reason: str) -> AutomationDecision:
        self._state = BoilerState.ERROR
        self._boiler_loading_started_at = None
        return AutomationDecision(
            state=self._state,
            cwu_circulation_on=False,
            boiler_loading_on=False,
            electric_heater_on=False,
            pellet_boiler_power_on=True,
            pellet_low=False,
            reason=reason,
        )

    def _evaluate_boiler_loading(
        self,
        inputs: AutomationInput,
        pellet_low: bool,
    ) -> AutomationDecision:
        if self._boiler_loading_started_at is None:
            return self.fail_safe("Brak czasu rozpoczęcia ładowania bojlera")

        elapsed = inputs.monotonic_seconds - self._boiler_loading_started_at
        if elapsed < self._boiler_loading_seconds:
            return self._decision(
                pellet_low=pellet_low,
                cwu_circulation_on=inputs.cwu_circulation_requested,
                boiler_loading_on=True,
                reason="Trwa czasowe ładowanie bojlera",
            )

        self._boiler_loading_started_at = None
        self._next_boiler_loading_check_at = (
            inputs.monotonic_seconds + self._boiler_loading_recheck_seconds
        )

        # Po zakończeniu ładowania grzałka może wystartować w tym samym cyklu,
        # ale nigdy równocześnie z pompą ładującą.
        if inputs.electric_heater_requested:
            self._state = BoilerState.ELECTRIC_HEATING
            return self._decision(
                pellet_low=pellet_low,
                cwu_circulation_on=inputs.cwu_circulation_requested,
                electric_heater_on=True,
                reason="Ładowanie zakończone; uruchomiono grzałkę na żądanie",
            )

        if inputs.pellet_heating_detected:
            self._state = BoilerState.PELLET_HEATING
            return self._decision(
                pellet_low=pellet_low,
                cwu_circulation_on=inputs.cwu_circulation_requested,
                reason="Ładowanie zakończone; następne sprawdzenie po przerwie",
            )

        self._state = BoilerState.IDLE
        return self._decision(
            pellet_low=pellet_low,
            cwu_circulation_on=inputs.cwu_circulation_requested,
            reason="Ładowanie zakończone; piec pelletowy nie grzeje",
        )

    def _decision(
        self,
        *,
        pellet_low: bool,
        cwu_circulation_on: bool = False,
        boiler_loading_on: bool = False,
        electric_heater_on: bool = False,
        reason: str,
    ) -> AutomationDecision:
        if boiler_loading_on and electric_heater_on:
            raise RuntimeError("Pompa ładująca i grzałka nie mogą pracować równocześnie")
        return AutomationDecision(
            state=self._state,
            cwu_circulation_on=cwu_circulation_on,
            boiler_loading_on=boiler_loading_on,
            electric_heater_on=electric_heater_on,
            pellet_boiler_power_on=getattr(self, "_pellet_boiler_power_on", True),
            pellet_low=pellet_low,
            reason=reason,
        )

    @staticmethod
    def _validate_input(inputs: AutomationInput) -> None:
        if not -55.0 <= inputs.pipe_temperature_c <= 125.0:
            raise ValueError(f"Temperatura rury poza zakresem: {inputs.pipe_temperature_c}°C")
        if not 0.0 <= inputs.pellet_level_percent <= 100.0:
            raise ValueError(f"Poziom pelletu poza zakresem: {inputs.pellet_level_percent}%")
        if inputs.monotonic_seconds < 0:
            raise ValueError("Czas monotoniczny nie może być ujemny")
