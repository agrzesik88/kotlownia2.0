from __future__ import annotations

import logging
from dataclasses import replace
from threading import Event
from time import monotonic
from typing import Callable

from controller.automation import AutomationController, AutomationDecision, AutomationInput
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
        self.other_requested = False
        self.cwu_circulation_requested = False
        self._last_pellet_notification_at: float | None = None
        self._pellet_was_low = False
        self._had_error = False
        self._last_history_recorded_at: float | None = None
        self._last_cwu_circulation_on: bool | None = None
        self._cwu_schedule_started_at: float | None = None
        self._last_cwu_schedule_active = False
        self._automation_settings_path = (
            config.application.state_file.parent / "automation_settings.json"
        )

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
                recipients=email.recipients,
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

        self.temperature = TemperatureSensor(config.temperature, config.temperature.simulation)
        self.pellet = PelletSensor(config.pellet, config.pellet.simulation)
        self.relays = RelayController(config.relays, config.application.simulation)
        self.automation = AutomationController(
            boiler_loading_temperature_c=config.automation.boiler_loading_temperature_c,
            boiler_loading_seconds=config.automation.boiler_loading_seconds,
            boiler_loading_recheck_seconds=config.automation.boiler_loading_recheck_seconds,
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

    def _load_runtime_automation_settings(self) -> None:
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

    def set_other_requested(self, requested: bool) -> None:
        self.other_requested = requested

    def set_cwu_circulation_requested(self, requested: bool) -> None:
        self.cwu_circulation_requested = requested

    def run_once(self) -> ControllerState:
        now = self.clock()
        try:
            self._load_runtime_automation_settings()
            temperature = self.temperature.read_celsius()
            pellet_level = self.pellet.read_level_percent()
            heating_detected = temperature >= self.config.temperature.heating_available_c
            schedule = self.scheduler.evaluate() if self.scheduler is not None else ScheduleDecision(False, False)
            manual = self.manual_control.evaluate() if self.manual_control is not None else ManualControlDecision()
            # Priorytet sterowania: RĘCZNE > HARMONOGRAM > AUTOMATYKA.
            # Automatyka dotyczy wyłącznie pompy bojlera.
            decision = self.automation.evaluate(
                AutomationInput(
                    pipe_temperature_c=temperature,
                    pellet_level_percent=pellet_level,
                    pellet_heating_detected=heating_detected,
                    monotonic_seconds=now,
                    boiler_loading_requested=False,
                    pellet_boiler_power_override=None,
                )
            )

            # Ręczne sterowanie ma zawsze pierwszeństwo.
            # Jeżeli nie ma ręcznego wymuszenia, harmonogram ma pierwszeństwo
            # przed automatyką. Cyrkulacja CWU i "Inne" nie są sterowane przez automatykę.
            decision = replace(
                decision,
                cwu_circulation_on=(
                    manual.cwu_circulation_requested
                    if manual.cwu_circulation_requested
                    else schedule.cwu_circulation_requested
                ),
                boiler_loading_on=(
                    manual.boiler_loading_requested
                    if manual.boiler_loading_requested
                    else decision.boiler_loading_on
                ),
                other_on=(
                    manual.other_requested
                    if manual.other_requested
                    else schedule.other_requested
                ),
                pellet_boiler_power_on=(
                    manual.pellet_boiler_power_override
                    if manual.pellet_boiler_power_override is not None
                    else decision.pellet_boiler_power_on
                ),
            )
            self.relays.apply(
                cwu_circulation_on=decision.cwu_circulation_on,
                boiler_loading_on=decision.boiler_loading_on,
                other_on=decision.other_on,
                pellet_boiler_power_on=decision.pellet_boiler_power_on,
            )
            self._record_cwu_schedule_transition(
                decision.cwu_circulation_on,
                schedule.cwu_circulation_requested,
                now,
            )

            self.state.pipe_temperature_c = temperature
            self.state.pellet_level_percent = pellet_level
            self.state.pellet_heating_detected = heating_detected
            self.state.pellet_low = decision.pellet_low
            self.state.automation_state = decision.state.name
            self.state.automation_reason = decision.reason
            self.state.scheduler_enabled = self.scheduler is not None
            self.state.cwu_schedule_active = schedule.cwu_circulation_requested
            self.state.other_schedule_active = schedule.other_requested
            self.state.manual_control_enabled = self.manual_control is not None
            self.state.cwu_manual_active = manual.cwu_circulation_requested
            self.state.other_manual_active = manual.other_requested
            self.state.boiler_loading_manual_active = manual.boiler_loading_requested
            self.state.pellet_boiler_power_manual_active = manual.pellet_boiler_power_override is not None
            self.state.pellet_boiler_power_manual_override = manual.pellet_boiler_power_override
            self.state.cwu_manual_until = manual.cwu_circulation_until
            self.state.other_manual_until = manual.other_until
            self.state.boiler_loading_manual_until = manual.boiler_loading_until
            self.state.pellet_boiler_power_manual_until = manual.pellet_boiler_power_until
            self._update_output_status(decision, schedule, manual)
            self.state.last_error = None
            self._publish_recovery_if_needed()
            self._update_pellet_events(now, pellet_level, decision.pellet_low)
        except Exception as exc:
            decision = self.automation.fail_safe(str(exc))
            self.relays.apply(
                cwu_circulation_on=decision.cwu_circulation_on,
                boiler_loading_on=decision.boiler_loading_on,
                other_on=decision.other_on,
                pellet_boiler_power_on=decision.pellet_boiler_power_on,
            )
            if self._last_cwu_circulation_on is True and self._cwu_schedule_started_at is not None:
                duration_seconds = max(0.0, now - self._cwu_schedule_started_at)
                self.event_bus.publish(
                    ControllerEvent(
                        EventType.CWU_CIRCULATION_SCHEDULE_STOPPED,
                        "Cyrkulacja CWU została wyłączona w trybie awaryjnym",
                        {
                            "output": "cwu_circulation",
                            "source": "HARMONOGRAM",
                            "duration_seconds": round(duration_seconds, 1),
                        },
                    )
                )
            self._last_cwu_circulation_on = False
            self._cwu_schedule_started_at = None
            self._last_cwu_schedule_active = False
            self.state.automation_state = decision.state.name
            self.state.automation_reason = decision.reason
            self.state.output_status = {
                "cwu_circulation": {"state": "OFF", "requested": "OFF", "mode": "AUTO", "reason": "Sterownik w trybie awaryjnym"},
                "boiler_loading": {"state": "OFF", "requested": "OFF", "mode": "AUTO", "reason": "Sterownik w trybie awaryjnym"},
                "other": {"state": "OFF", "requested": "OFF", "mode": "AUTO", "reason": "Sterownik w trybie awaryjnym"},
                "pellet_boiler_power": {"state": "ON", "requested": "ON", "mode": "AUTO", "reason": "Tryb awaryjny pozostawia zasilanie pieca włączone"},
            }
            self.state.last_error = str(exc)
            self.state.alerts = [{"severity": "ERROR", "code": "CONTROLLER_ERROR", "message": f"Błąd sterownika: {exc}"}]
            if not self._had_error:
                self.event_bus.publish(ControllerEvent(EventType.CONTROLLER_ERROR, f"Błąd sterownika: {exc}", {"error": str(exc)}))
            self._had_error = True
        finally:
            self.state.pellet_sensor_consecutive_failures = self.pellet.consecutive_failures
            self.state.pellet_sensor_stale = self.pellet.using_last_good_value
            self._update_alerts()
            self._copy_relay_state()
            self.state.update_timestamp()
            self.state.save(self.config.application.state_file)
            self._record_history_if_due(now)
        return self.state

    def _record_cwu_schedule_transition(
        self,
        cwu_circulation_on: bool,
        schedule_active: bool,
        now: float,
    ) -> None:
        previous = self._last_cwu_circulation_on
        if cwu_circulation_on and schedule_active and previous is not True:
            self._cwu_schedule_started_at = now
            self.event_bus.publish(
                ControllerEvent(
                    EventType.CWU_CIRCULATION_SCHEDULE_STARTED,
                    "Cyrkulacja CWU została włączona przez harmonogram",
                    {"output": "cwu_circulation", "source": "HARMONOGRAM"},
                )
            )
        elif self._last_cwu_schedule_active and not schedule_active and self._cwu_schedule_started_at is not None:
            duration_seconds = max(0.0, now - self._cwu_schedule_started_at)
            self.event_bus.publish(
                ControllerEvent(
                    EventType.CWU_CIRCULATION_SCHEDULE_STOPPED,
                    "Cyrkulacja CWU została wyłączona po zakończeniu harmonogramu",
                    {
                        "output": "cwu_circulation",
                        "source": "HARMONOGRAM",
                        "duration_seconds": round(duration_seconds, 1),
                    },
                )
            )
            self._cwu_schedule_started_at = None
        self._last_cwu_circulation_on = cwu_circulation_on
        self._last_cwu_schedule_active = schedule_active

    def _update_output_status(self, decision: AutomationDecision, schedule: ScheduleDecision, manual: ManualControlDecision) -> None:
        if schedule.cwu_circulation_requested:
            cwu_mode = "HARMONOGRAM"
            cwu_reason = "Harmonogram ma pierwszeństwo"
        elif manual.cwu_circulation_requested:
            cwu_mode = "RĘCZNY"
            cwu_reason = "Aktywne żądanie ręczne"
        else:
            cwu_mode = "AUTO"
            cwu_reason = "Brak żądania cyrkulacji"

        if manual.boiler_loading_requested:
            boiler_mode = "RĘCZNY"
            boiler_reason = "Pompa bojlera pracuje na żądanie ręczne"
        elif decision.boiler_loading_on:
            boiler_mode = "AUTO"
            boiler_reason = decision.reason
        else:
            boiler_mode = "AUTO"
            boiler_reason = "Automatyka nie wymaga teraz ładowania bojlera"

        if schedule.other_requested:
            other_mode = "HARMONOGRAM"
            other_reason = "Harmonogram ma pierwszeństwo"
        elif manual.other_requested:
            other_mode = "RĘCZNY"
            other_reason = "Aktywne żądanie ręczne"
        else:
            other_mode = "AUTO"
            other_reason = "Brak żądania"
        other_requested = schedule.other_requested or manual.other_requested

        if manual.pellet_boiler_power_override is not None:
            power_mode = "RĘCZNY"
            power_reason = "Wymuszone włączenie ręczne" if manual.pellet_boiler_power_override else "Wymuszone wyłączenie ręczne"
        else:
            power_mode = "AUTO"
            power_reason = "Zasilanie sterowane automatycznie"

        self.state.output_status = {
            "cwu_circulation": {
                "state": "ON" if decision.cwu_circulation_on else "OFF",
                "requested": "ON" if (manual.cwu_circulation_requested or schedule.cwu_circulation_requested) else "OFF",
                "mode": cwu_mode,
                "reason": cwu_reason,
            },
            "boiler_loading": {
                "state": "ON" if decision.boiler_loading_on else "OFF",
                "requested": "ON" if (manual.boiler_loading_requested or decision.boiler_loading_on) else "OFF",
                "mode": boiler_mode,
                "reason": boiler_reason,
            },
            "other": {
                "state": "ON" if decision.other_on else "OFF",
                "requested": "ON" if other_requested else "OFF",
                "mode": other_mode,
                "reason": other_reason,
            },
            "pellet_boiler_power": {
                "state": "ON" if decision.pellet_boiler_power_on else "OFF",
                "requested": "ON" if decision.pellet_boiler_power_on else "OFF",
                "mode": power_mode,
                "reason": power_reason,
            },
        }

    def _update_alerts(self) -> None:
        alerts: list[dict[str, str]] = []
        if self.state.pellet_low:
            alerts.append({"severity": "WARNING", "code": "PELLET_LOW", "message": f"Niski poziom pelletu: {self.state.pellet_level_percent:.1f}%"})
        if self.state.pellet_sensor_stale:
            alerts.append({"severity": "WARNING", "code": "PELLET_SENSOR_STALE", "message": "HC-SR04 nie dostarcza poprawnych pomiarów. Używany jest ostatni poprawny odczyt " f"({self.state.pellet_sensor_consecutive_failures} błędów)."})
        if self.state.last_error:
            alerts.append({"severity": "ERROR", "code": "CONTROLLER_ERROR", "message": f"Błąd sterownika: {self.state.last_error}"})
        self.state.alerts = alerts

    def _publish_recovery_if_needed(self) -> None:
        if not self._had_error:
            return
        self._had_error = False
        self.event_bus.publish(ControllerEvent(EventType.CONTROLLER_RECOVERED, "Sterownik wrócił do prawidłowej pracy"))

    def _update_pellet_events(self, now: float, pellet_level_percent: float, pellet_low: bool) -> None:
        if not pellet_low:
            if self._pellet_was_low:
                self.event_bus.publish(ControllerEvent(EventType.PELLET_RECOVERED, "Poziom pelletu wrócił powyżej progu alarmowego", {"pellet_level_percent": pellet_level_percent}))
            self._pellet_was_low = False
            self._last_pellet_notification_at = None
            return
        if not self._pellet_was_low:
            self.event_bus.publish(ControllerEvent(EventType.PELLET_LOW, f"Niski poziom pelletu: {pellet_level_percent:.1f}%", {"pellet_level_percent": pellet_level_percent}))
            self._last_pellet_notification_at = now
        elif self._last_pellet_notification_at is None or now - self._last_pellet_notification_at >= self.config.automation.pellet_low_reminder_seconds:
            self.notifications.send_email("Kotłownia 2.0: nadal niski poziom pelletu", f"Poziom pelletu nadal wynosi tylko {pellet_level_percent:.1f}%. Uzupełnij zasobnik.")
            self._last_pellet_notification_at = now
        self._pellet_was_low = True

    def _handle_event(self, event: ControllerEvent) -> None:
        if self.history is not None:
            self.history.record_event(event)
        if event.event_type is EventType.PELLET_LOW:
            self.notifications.warning(event.message)
            self.notifications.send_email("Kotłownia 2.0: niski poziom pelletu", event.message + ". Uzupełnij zasobnik.")
        elif event.event_type is EventType.CONTROLLER_ERROR:
            self.notifications.error(event.message)
            self.notifications.send_email("Kotłownia 2.0: błąd sterownika", event.message)
        else:
            self.notifications.info(event.message)

    def _record_history_if_due(self, now: float) -> None:
        if self.history is None:
            return
        interval = self.config.history.sample_interval_seconds
        if interval <= 0 or self._last_history_recorded_at is None or now - self._last_history_recorded_at >= interval:
            self.history.record_state(self.state)
            self._last_history_recorded_at = now

    def _copy_relay_state(self) -> None:
        relay_state = self.relays.state
        self.state.cwu_circulation_on = relay_state.cwu_circulation_on
        self.state.boiler_loading_on = relay_state.boiler_loading_on
        self.state.other_on = relay_state.other_on
        self.state.pellet_boiler_power_on = relay_state.pellet_boiler_power_on

    def run(self) -> None:
        self.notifications.info(f"{self.config.application.name} uruchomiona; symulacja={self.config.application.simulation}")
        while not self.stop_event.is_set():
            state = self.run_once()
            if state.pellet_sensor_stale:
                logging.warning("HC-SR04: używam ostatniego poprawnego pomiaru; kolejne błędy=%s", state.pellet_sensor_consecutive_failures)
            logging.info("Temperatura=%s°C, pellet=%s%%, automat=%s, powód=%s", state.pipe_temperature_c, state.pellet_level_percent, state.automation_state, state.automation_reason)
            self.stop_event.wait(self.config.application.loop_interval_seconds)

    def close(self) -> None:
        self.pellet.close()
        self.relays.close()
        if self.history is not None:
            self.history.close()
