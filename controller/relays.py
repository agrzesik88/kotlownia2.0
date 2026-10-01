from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Protocol

from controller.config import RelayConfig


logger = logging.getLogger(__name__)


class OutputPin(Protocol):
    def on(self) -> None: ...
    def off(self) -> None: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class RelayState:
    cwu_circulation_on: bool = False
    boiler_loading_on: bool = False
    other_on: bool = False
    pellet_boiler_power_on: bool = True


class RelayController:
    """Steruje przekaźnikami i wykonuje tylko rzeczywiste zmiany stanu."""

    def __init__(self, config: RelayConfig, simulation: bool = True) -> None:
        self.config = config
        self.simulation = simulation
        self.state = RelayState()
        self._pins: dict[str, OutputPin] = {}
        self._applied: dict[str, bool | None] = {
            "cwu": None,
            "loading": None,
            "other": None,
            "pellet_power": None,
        }
        self._closed = False

        if not simulation:
            self._initialize_gpio()

        # Pierwsze wywołanie zawsze fizycznie ustawia bezpieczny stan,
        # ponieważ stan wyjść przed inicjalizacją jest nieznany.
        self.all_safe()

    def _initialize_gpio(self) -> None:
        try:
            from gpiozero import OutputDevice
        except ImportError as exc:
            raise RuntimeError(
                "Brak gpiozero. Zainstaluj zależności sprzętowe przed wyłączeniem symulacji."
            ) from exc

        active_high = not self.config.active_low
        common = {"active_high": active_high, "initial_value": False}
        self._pins = {
            "cwu": OutputDevice(self.config.cwu_circulation_gpio, **common),
            "loading": OutputDevice(self.config.boiler_loading_gpio, **common),
            "other": OutputDevice(self.config.other_gpio, **common),
            "pellet_power": OutputDevice(self.config.pellet_boiler_power_gpio, **common),
        }

    def _set(self, key: str, label: str, enabled: bool) -> bool:
        if self._closed:
            raise RuntimeError("Sterownik przekaźników jest już zamknięty")

        if self._applied[key] is enabled:
            return False

        if self.simulation:
            logger.info(
                "[SYMULACJA] %s -> %s",
                label,
                "WŁĄCZONE" if enabled else "WYŁĄCZONE",
            )
        else:
            pin = self._pins[key]
            pin.on() if enabled else pin.off()
            logger.info(
                "%s -> %s",
                label,
                "WŁĄCZONE" if enabled else "WYŁĄCZONE",
            )

        self._applied[key] = enabled
        return True

    def set_cwu_circulation(self, enabled: bool) -> bool:
        changed = self._set("cwu", "Pompa cyrkulacyjna CWU", enabled)
        self.state.cwu_circulation_on = enabled
        return changed

    def set_boiler_loading(self, enabled: bool) -> bool:
        changed = self._set("loading", "Pompa ładująca bojler", enabled)
        self.state.boiler_loading_on = enabled
        return changed

    def set_other(self, enabled: bool) -> bool:
        changed = self._set("other", "Inne", enabled)
        self.state.other_on = enabled
        return changed

    def set_pellet_boiler_power(self, enabled: bool) -> bool:
        changed = self._set("pellet_power", "Zasilanie pieca pelletowego", enabled)
        self.state.pellet_boiler_power_on = enabled
        return changed

    def apply(
        self,
        *,
        cwu_circulation_on: bool,
        boiler_loading_on: bool,
        other_on: bool,
        pellet_boiler_power_on: bool,
    ) -> bool:
        if boiler_loading_on and other_on:
            raise ValueError(
                "Pompa ładująca i inne nie mogą pracować równocześnie"
            )

        changed = False
        changed |= self.set_cwu_circulation(cwu_circulation_on)
        changed |= self.set_boiler_loading(boiler_loading_on)
        changed |= self.set_other(other_on)
        changed |= self.set_pellet_boiler_power(pellet_boiler_power_on)
        return changed

    def all_safe(self) -> bool:
        return self.apply(
            cwu_circulation_on=False,
            boiler_loading_on=False,
            other_on=False,
            pellet_boiler_power_on=True,
        )

    def close(self) -> None:
        if self._closed:
            return

        self.all_safe()
        for pin in self._pins.values():
            pin.close()
        self._pins.clear()
        self._closed = True
