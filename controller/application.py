from __future__ import annotations

import logging
from threading import Event
from time import monotonic
from typing import Callable

from controller.automation import AutomationController, AutomationInput
from controller.config import ControllerConfig
from controller.events import ControllerEvent, EventBus, EventType
from controller.history import HistoryRepository
from controller.manual import ManualControlDecision, ManualControlRepository
from controller.notifications import EmailConfig, NotificationService
from controller.pellet import PelletSensor
from controller.relays import RelayController
from controller.scheduler import ScheduleDecision, ScheduleRepository, TimeScheduler
from controller.state import ControllerState
from controller.temperature import TemperatureSensor


class ControllerApplication:
    """Orkiestruje sprzęt i automatykę; nie zawiera reguł sterowania."""

    def __init__(
        self,
        config: ControllerConfig,
        *,
        clock: Callable[[], float] = monotonic,
        event_bus: EventBus | None = None,
        history: HistoryRepository | None = None,
    ) -> None:
        self.config = config
        self.stop_event = Event()
        self.clock = clock
        self.electric_heater_requested = False
        self.cwu_circulation_requested = False
        self._last_pellet_notification_at: float | None = None
        self._pellet_was_low = False
        self._had_error = False
        self._last_history_recorded_at: float | None = None

        email = config.email_notifications
        self.notifications = NotificationService(
            EmailConfig(
                enabled=email.enabled,
                smtp_host=email.smtp_host,
                smtp_port=email.smtp_port,
                use_starttls=email.use_starttls,
                username_env=email.username_env,
                password_env=email.password_env,
                sender=email.sender,
                recipient=email.recipient,
            )
        )

        self.event_bus = event_bus or EventBus()
        if history is not None:
            self.history = history
        elif config.history.enabled:
            self.history = HistoryRepository(config.history.database_file)
        else:
            self.history = None
        self.event_bus.subscribe(self._handle_event)

        # Czujniki są inicjalizowane przed przekaźnikami. Brak zależności
        # sprzętowej nie może spowodować nawet chwilowego przełączenia wyjść.
        self.temperature = TemperatureSensor(
            config.temperature, config.temperature.simulation
        )
        self.pellet = PelletSensor(config.pellet, config.pellet.simulation)
        self.relays = RelayController(config.relays, config.application.simulation)
        self.automation = AutomationController(
            boiler_loading_temperature_c=(
                config.automation.boiler_loading_temperature_c
            ),
            boiler_loading_seconds=config.automation.boiler_loading_seconds,
            boiler_loading_recheck_seconds=(
                config.automation.boiler_loading_recheck_seconds
            ),
            pellet_low_level_percent=config.automation.pellet_low_level_percent,
        )
        self.manual_control = (
            ManualControlRepository(config.manual_control.command_file)
            if config.manual_control.enabled
            else None
        )
        self.scheduler = (
            TimeScheduler(ScheduleRepository(config.scheduler.schedule_file))
            if config.scheduler.enabled
            else None
        )
        self.state = ControllerState(
            simulation_mode=config.application.simulation,
            scheduler_enabled=config.scheduler.enabled,
            manual_control_enabled=config.manual_control.enabled,
        )

    def request_stop(self, *_args: object) -> None:
        self.stop_event.set()

    def set_electric_heater_requested(self, requested: bool) -> None:
        """Ręczne żądanie używane przez przyszłe API/tryb serwisowy."""
        self.electric_heater_requested = requested

    def set_cwu_circulation_requested(self, requested: bool) -> None:
        self.cwu_circulation_requested = requested

    def run_once(self) -> ControllerState:
        now = self.clock()
        try:
            self._load_runtime_automation_settings()
            temperature = self.temperature.read_celsius()
            pellet_level = self.pellet.read_level_percent()
            heating_detected = (
                temperature >= self.config.temperature.heating_available_c
            )
            schedule = (
                self.scheduler.evaluate()
                if self.scheduler is not None
                else ScheduleDecision(False, False)
            )
            manual = (
                self.manual_control.evaluate()
                if self.manual_control is not None
                else ManualControlDecision()
            )
            electric_heater_requested = (
                self.electric_heater_requested
                or schedule.electric_heater_requested
                or manual.electric_heater_requested
            )
            cwu_circulation_requested = (
                self.cwu_circulation_requested
                or schedule.cwu_circulation_requested
                or manual.cwu_circulation_requested
            )

            decision = self.automation.evaluate(
                AutomationInput(
                    pipe_temperature_c=temperature,
                    pellet_level_percent=pellet_level,
                    pellet_heating_detected=heating_detected,
                    monotonic_seconds=now,
                    electric_heater_requested=electric_heater_requested,
                    cwu_circulation_requested=cwu_circulation_requested,
                    boiler_loading_requested=manual.boiler_loading_requested,
                    pellet_boiler_power_override=manual.pellet_boiler_power_override,
                )
            )
            self.relays.apply(
                cwu_circulation_on=decision.cwu_circulation_on,
                boiler_loading_on=decision.boiler_loading_on,
                electric_heater_on=decision.electric_heater_on,
                pellet_boiler_power_on=decision.pellet_boiler_power_on,
            )

            self.state.pipe_temperature_c = temperature
            self.state.pellet_level_percent = pellet_level
            self.state.pellet_heating_detected = heating_detected
            self.state.pellet_low = decision.pellet_low
            self.state.automation_state = decision.state.name
            self.state.automation_reason = decision.reason
            self.state.scheduler_enabled = self.scheduler is not None
            self.state.cwu_schedule_active = schedule.cwu_circulation_requested
            self.state.electric_heater_schedule_active = schedule.electric_heater_requested
            self.state.manual_control_enabled = self.manual_control is not None
            self.state.cwu_manual_active = manual.cwu_circulation_requested
            self.state.electric_heater_manual_active = manual.electric_heater_requested
            self.state.boiler_loading_manual_active = manual.boiler_loading_requested
            self.state.pellet_boiler_power_manual_active = (manual.pellet_boiler_power_override is not None)
            self.state.pellet_boiler_power_manual_override = manual.pellet_boiler_power_override
            self.state.cwu_manual_until = manual.cwu_circulation_until
            self.state.electric_heater_manual_until = manual.electric_heater_until
            self.state.boiler_loading_manual_until = manual.boiler_loading_until
            self.state.pellet_boiler_power_manual_until = manual.pellet_boiler_power_until
            self.state.last_error = None
            self._publish_recovery_if_needed()
            self._update_pellet_events(now, pellet_level, decision.pellet_low)
        except Exception as exc:
            decision = self.automation.fail_safe(str(exc))
            self.relays.apply(
                cwu_circulation_on=decision.cwu_circulation_on,
                boiler_loading_on=decision.boiler_loading_on,
                electric_heater_on=decision.electric_heater_on,
                pellet_boiler_power_on=decision.pellet_boiler_power_on,
            )
            self.state.automation_state = decision.state.name
            self.state.automation_reason = decision.reason
            self.state.last_error = str(exc)
            if not self._had_error:
                self.event_bus.publish(
                    ControllerEvent(
                        EventType.CONTROLLER_ERROR,
                        f"Błąd sterownika: {exc}",
                        {"error": str(exc)},
                    )
                )
            self._had_error = True
        finally:
            self.state.pellet_sensor_consecutive_failures = (
                self.pellet.consecutive_failures
            )
            self.state.pellet_sensor_stale = self.pellet.using_last_good_value
            self._copy_relay_state()
            self.state.update_timestamp()
            self.state.save(self.config.application.state_file)
            self._record_history_if_due(now)
        return self.state

    def _publish_recovery_if_needed(self) -> None:
        if not self._had_error:
            return
        self._had_error = False
        self.event_bus.publish(
            ControllerEvent(
                EventType.CONTROLLER_RECOVERED,
                "Sterownik wrócił do prawidłowej pracy",
            )
        )

    def _update_pellet_events(
        self,
        now: float,
        pellet_level_percent: float,
        pellet_low: bool,
    ) -> None:
        if not pellet_low:
            if self._pellet_was_low:
                self.event_bus.publish(
                    ControllerEvent(
                        EventType.PELLET_RECOVERED,
                        "Poziom pelletu wrócił powyżej progu alarmowego",
                        {"pellet_level_percent": pellet_level_percent},
                    )
                )
            self._pellet_was_low = False
            self._last_pellet_notification_at = None
            return

        if not self._pellet_was_low:
            self.event_bus.publish(
                ControllerEvent(
                    EventType.PELLET_LOW,
                    f"Niski poziom pelletu: {pellet_level_percent:.1f}%",
                    {"pellet_level_percent": pellet_level_percent},
                )
            )
            self._last_pellet_notification_at = now
        elif (
            self._last_pellet_notification_at is None
            or now - self._last_pellet_notification_at
            >= self.config.automation.pellet_low_reminder_seconds
        ):
            self.notifications.send_email(
                "Kotłownia 2.0: nadal niski poziom pelletu",
                (
                    "Poziom pelletu nadal wynosi tylko "
                    f"{pellet_level_percent:.1f}%. Uzupełnij zasobnik."
                ),
            )
            self._last_pellet_notification_at = now
        self._pellet_was_low = True

    def _handle_event(self, event: ControllerEvent) -> None:
        if self.history is not None:
            self.history.record_event(event)

        if event.event_type is EventType.PELLET_LOW:
            self.notifications.warning(event.message)
            self.notifications.send_email(
                "Kotłownia 2.0: niski poziom pelletu",
                event.message + ". Uzupełnij zasobnik.",
            )
        elif event.event_type is EventType.CONTROLLER_ERROR:
            self.notifications.error(event.message)
            self.notifications.send_email(
                "Kotłownia 2.0: błąd sterownika",
                event.message,
            )
        else:
            self.notifications.info(event.message)

    def _record_history_if_due(self, now: float) -> None:
        if self.history is None:
            return
        interval = self.config.history.sample_interval_seconds
        if interval <= 0:
            self.history.record_state(self.state)
            self._last_history_recorded_at = now
            return
        if (
            self._last_history_recorded_at is None
            or now - self._last_history_recorded_at >= interval
        ):
            self.history.record_state(self.state)
            self._last_history_recorded_at = now

    def _copy_relay_state(self) -> None:
        relay_state = self.relays.state
        self.state.cwu_circulation_on = relay_state.cwu_circulation_on
        self.state.boiler_loading_on = relay_state.boiler_loading_on
        self.state.electric_heater_on = relay_state.electric_heater_on
        self.state.pellet_boiler_power_on = relay_state.pellet_boiler_power_on

    def run(self) -> None:
        self.notifications.info(
            f"{self.config.application.name} uruchomiona; "
            f"symulacja={self.config.application.simulation}"
        )
        while not self.stop_event.is_set():
            state = self.run_once()
            if state.pellet_sensor_stale:
                logging.warning(
                    "HC-SR04: używam ostatniego poprawnego pomiaru; "
                    "kolejne błędy=%s",
                    state.pellet_sensor_consecutive_failures,
                )
            logging.info(
                "Temperatura=%s°C, pellet=%s%%, automat=%s, powód=%s",
                state.pipe_temperature_c,
                state.pellet_level_percent,
                state.automation_state,
                state.automation_reason,
            )
            self.stop_event.wait(self.config.application.loop_interval_seconds)

    def close(self) -> None:
        self.pellet.close()
        self.relays.close()
        if self.history is not None:
            self.history.close()    def _load_runtime_automation_settings(self) -> None:
        if not self._automation_settings_path.is_file():
            return
        import json

        try:
            raw = json.loads(self._automation_settings_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            self.automation.update_settings(
                boiler_loading_temperature_c=float(raw["boiler_loading_temperature_c"]),
                boiler_loading_seconds=float(raw["boiler_loading_seconds"]),
                boiler_loading_recheck_seconds=float(raw["boiler_loading_recheck_seconds"]),
                pellet_low_level_percent=float(raw["pellet_low_level_percent"]),
            )
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            logging.warning("Nie udało się odczytać ustawień automatyki: %s", exc)

    def request_stop(self, *_args: object) -> None:
        self.stop_event.set()

    def set_electric_heater_requested(self, requested: bool) -> None:
        """Ręczne żądanie używane przez przyszłe API/tryb serwisowy."""
        self.electric_heater_requested = requested

    def set_cwu_circulation_requested(self, requested: bool) -> None:
        self.cwu_circulation_requested = requested

    def run_once(self) -> ControllerState:
        now = self.clock()
        try:
            temperature = self.temperature.read_celsius()
            pellet_level = self.pellet.read_level_percent()
            heating_detected = (
                temperature >= self.config.temperature.heating_available_c
            )
            schedule = (
                self.scheduler.evaluate()
                if self.scheduler is not None
                else ScheduleDecision(False, False)
            )
            manual = (
                self.manual_control.evaluate()
                if self.manual_control is not None
                else ManualControlDecision()
            )
            electric_heater_requested = (
                self.electric_heater_requested
                or schedule.electric_heater_requested
                or manual.electric_heater_requested
            )
            cwu_circulation_requested = (
                self.cwu_circulation_requested
                or schedule.cwu_circulation_requested
                or manual.cwu_circulation_requested
            )

            decision = self.automation.evaluate(
                AutomationInput(
                    pipe_temperature_c=temperature,
                    pellet_level_percent=pellet_level,
                    pellet_heating_detected=heating_detected,
                    monotonic_seconds=now,
                    electric_heater_requested=electric_heater_requested,
                    cwu_circulation_requested=cwu_circulation_requested,
                    boiler_loading_requested=manual.boiler_loading_requested,
                    pellet_boiler_power_override=manual.pellet_boiler_power_override,
                )
            )
            self.relays.apply(
                cwu_circulation_on=decision.cwu_circulation_on,
                boiler_loading_on=decision.boiler_loading_on,
                electric_heater_on=decision.electric_heater_on,
                pellet_boiler_power_on=decision.pellet_boiler_power_on,
            )

            self.state.pipe_temperature_c = temperature
            self.state.pellet_level_percent = pellet_level
            self.state.pellet_heating_detected = heating_detected
            self.state.pellet_low = decision.pellet_low
            self.state.automation_state = decision.state.name
            self.state.automation_reason = decision.reason
            self.state.scheduler_enabled = self.scheduler is not None
            self.state.cwu_schedule_active = schedule.cwu_circulation_requested
            self.state.electric_heater_schedule_active = schedule.electric_heater_requested
            self.state.manual_control_enabled = self.manual_control is not None
            self.state.cwu_manual_active = manual.cwu_circulation_requested
            self.state.electric_heater_manual_active = manual.electric_heater_requested
            self.state.boiler_loading_manual_active = manual.boiler_loading_requested
            self.state.pellet_boiler_power_manual_active = (manual.pellet_boiler_power_override is not None)
            self.state.pellet_boiler_power_manual_override = manual.pellet_boiler_power_override
            self.state.cwu_manual_until = manual.cwu_circulation_until
            self.state.electric_heater_manual_until = manual.electric_heater_until
            self.state.boiler_loading_manual_until = manual.boiler_loading_until
            self.state.pellet_boiler_power_manual_until = manual.pellet_boiler_power_until
            self.state.last_error = None
            self._publish_recovery_if_needed()
            self._update_pellet_events(now, pellet_level, decision.pellet_low)
        except Exception as exc:
            decision = self.automation.fail_safe(str(exc))
            self.relays.apply(
                cwu_circulation_on=decision.cwu_circulation_on,
                boiler_loading_on=decision.boiler_loading_on,
                electric_heater_on=decision.electric_heater_on,
                pellet_boiler_power_on=decision.pellet_boiler_power_on,
            )
            self.state.automation_state = decision.state.name
            self.state.automation_reason = decision.reason
            self.state.last_error = str(exc)
            if not self._had_error:
                self.event_bus.publish(
                    ControllerEvent(
                        EventType.CONTROLLER_ERROR,
                        f"Błąd sterownika: {exc}",
                        {"error": str(exc)},
                    )
                )
            self._had_error = True
        finally:
            self.state.pellet_sensor_consecutive_failures = (
                self.pellet.consecutive_failures
            )
            self.state.pellet_sensor_stale = self.pellet.using_last_good_value
            self._copy_relay_state()
            self.state.update_timestamp()
            self.state.save(self.config.application.state_file)
            self._record_history_if_due(now)
        return self.state

    def _publish_recovery_if_needed(self) -> None:
        if not self._had_error:
            return
        self._had_error = False
        self.event_bus.publish(
            ControllerEvent(
                EventType.CONTROLLER_RECOVERED,
                "Sterownik wrócił do prawidłowej pracy",
            )
        )

    def _update_pellet_events(
        self,
        now: float,
        pellet_level_percent: float,
        pellet_low: bool,
    ) -> None:
        if not pellet_low:
            if self._pellet_was_low:
                self.event_bus.publish(
                    ControllerEvent(
                        EventType.PELLET_RECOVERED,
                        "Poziom pelletu wrócił powyżej progu alarmowego",
                        {"pellet_level_percent": pellet_level_percent},
                    )
                )
            self._pellet_was_low = False
            self._last_pellet_notification_at = None
            return

        if not self._pellet_was_low:
            self.event_bus.publish(
                ControllerEvent(
                    EventType.PELLET_LOW,
                    f"Niski poziom pelletu: {pellet_level_percent:.1f}%",
                    {"pellet_level_percent": pellet_level_percent},
                )
            )
            self._last_pellet_notification_at = now
        elif (
            self._last_pellet_notification_at is None
            or now - self._last_pellet_notification_at
            >= self.config.automation.pellet_low_reminder_seconds
        ):
            self.notifications.send_email(
                "Kotłownia 2.0: nadal niski poziom pelletu",
                (
                    "Poziom pelletu nadal wynosi tylko "
                    f"{pellet_level_percent:.1f}%. Uzupełnij zasobnik."
                ),
            )
            self._last_pellet_notification_at = now
        self._pellet_was_low = True

    def _handle_event(self, event: ControllerEvent) -> None:
        if self.history is not None:
            self.history.record_event(event)

        if event.event_type is EventType.PELLET_LOW:
            self.notifications.warning(event.message)
            self.notifications.send_email(
                "Kotłownia 2.0: niski poziom pelletu",
                event.message + ". Uzupełnij zasobnik.",
            )
        elif event.event_type is EventType.CONTROLLER_ERROR:
            self.notifications.error(event.message)
            self.notifications.send_email(
                "Kotłownia 2.0: błąd sterownika",
                event.message,
            )
        else:
            self.notifications.info(event.message)

    def _record_history_if_due(self, now: float) -> None:
        if self.history is None:
            return
        interval = self.config.history.sample_interval_seconds
        if interval <= 0:
            self.history.record_state(self.state)
            self._last_history_recorded_at = now
            return
        if (
            self._last_history_recorded_at is None
            or now - self._last_history_recorded_at >= interval
        ):
            self.history.record_state(self.state)
            self._last_history_recorded_at = now

    def _copy_relay_state(self) -> None:
        relay_state = self.relays.state
        self.state.cwu_circulation_on = relay_state.cwu_circulation_on
        self.state.boiler_loading_on = relay_state.boiler_loading_on
        self.state.electric_heater_on = relay_state.electric_heater_on
        self.state.pellet_boiler_power_on = relay_state.pellet_boiler_power_on

    def run(self) -> None:
        self.notifications.info(
            f"{self.config.application.name} uruchomiona; "
            f"symulacja={self.config.application.simulation}"
        )
        while not self.stop_event.is_set():
            state = self.run_once()
            if state.pellet_sensor_stale:
                logging.warning(
                    "HC-SR04: używam ostatniego poprawnego pomiaru; "
                    "kolejne błędy=%s",
                    state.pellet_sensor_consecutive_failures,
                )
            logging.info(
                "Temperatura=%s°C, pellet=%s%%, automat=%s, powód=%s",
                state.pipe_temperature_c,
                state.pellet_level_percent,
                state.automation_state,
                state.automation_reason,
            )
            self.stop_event.wait(self.config.application.loop_interval_seconds)

    def close(self) -> None:
        self.pellet.close()
        self.relays.close()
        if self.history is not None:
            self.history.close()
