from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    name: str
    simulation: bool
    state_file: Path
    loop_interval_seconds: float


@dataclass(frozen=True, slots=True)
class TemperatureConfig:
    simulation: bool
    heating_available_c: float
    read_interval_seconds: float
    sensor_file: Path | None
    simulation_value_c: float


@dataclass(frozen=True, slots=True)
class PelletConfig:
    simulation: bool
    trigger_gpio: int
    echo_gpio: int
    empty_distance_cm: float
    full_distance_cm: float
    sample_count: int
    minimum_valid_samples: int
    max_consecutive_failures: int
    sample_interval_seconds: float
    simulation_level_percent: float


@dataclass(frozen=True, slots=True)
class RelayConfig:
    active_low: bool
    cwu_circulation_gpio: int
    boiler_loading_gpio: int
    electric_heater_gpio: int
    pellet_boiler_power_gpio: int


@dataclass(frozen=True, slots=True)
class AutomationConfig:
    boiler_loading_temperature_c: float
    boiler_loading_seconds: int
    boiler_loading_recheck_seconds: int
    pellet_low_level_percent: float
    pellet_low_reminder_seconds: int


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    enabled: bool
    schedule_file: Path


@dataclass(frozen=True, slots=True)
class ManualControlConfig:
    enabled: bool
    command_file: Path


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    enabled: bool
    database_file: Path
    sample_interval_seconds: float


@dataclass(frozen=True, slots=True)
class EmailNotificationConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    use_starttls: bool
    username_env: str
    password_env: str
    sender: str
    recipient: str


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    application: ApplicationConfig
    temperature: TemperatureConfig
    pellet: PelletConfig
    relays: RelayConfig
    automation: AutomationConfig
    scheduler: SchedulerConfig
    manual_control: ManualControlConfig
    history: HistoryConfig
    email_notifications: EmailNotificationConfig


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"Brak wymaganej sekcji [{name}] w konfiguracji")
    return value


def load_config(path: str | Path = "config/settings.toml") -> ControllerConfig:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Nie znaleziono pliku konfiguracji: {config_path.resolve()}")

    with config_path.open("rb") as file:
        raw: dict[str, Any] = tomllib.load(file)

    application = _section(raw, "application")
    temperature = _section(raw, "temperature")
    pellet = _section(raw, "pellet")
    relays = _section(raw, "relays")
    automation = _section(raw, "automation")
    scheduler = _section(raw, "scheduler")
    manual_control = _section(raw, "manual_control")
    history = _section(raw, "history")
    email_notifications = _section(raw, "email_notifications")

    sensor_file_value = temperature.get("sensor_file")
    sensor_file = Path(str(sensor_file_value)) if sensor_file_value else None

    return ControllerConfig(
        application=ApplicationConfig(
            name=str(application["name"]),
            simulation=bool(application["simulation"]),
            state_file=Path(str(application["state_file"])),
            loop_interval_seconds=float(application.get("loop_interval_seconds", 1.0)),
        ),
        temperature=TemperatureConfig(
            simulation=bool(temperature.get("simulation", application["simulation"])),
            heating_available_c=float(temperature["heating_available_c"]),
            read_interval_seconds=float(temperature["read_interval_seconds"]),
            sensor_file=sensor_file,
            simulation_value_c=float(temperature.get("simulation_value_c", 20.0)),
        ),
        pellet=PelletConfig(
            simulation=bool(pellet.get("simulation", application["simulation"])),
            trigger_gpio=int(pellet["trigger_gpio"]),
            echo_gpio=int(pellet["echo_gpio"]),
            empty_distance_cm=float(pellet.get("empty_distance_cm", 100.0)),
            full_distance_cm=float(pellet.get("full_distance_cm", 10.0)),
            sample_count=int(pellet.get("sample_count", 5)),
            minimum_valid_samples=int(pellet.get("minimum_valid_samples", 3)),
            max_consecutive_failures=int(
                pellet.get("max_consecutive_failures", 5)
            ),
            sample_interval_seconds=float(
                pellet.get("sample_interval_seconds", 0.05)
            ),
            simulation_level_percent=float(
                pellet.get("simulation_level_percent", 75.0)
            ),
        ),
        relays=RelayConfig(
            active_low=bool(relays["active_low"]),
            cwu_circulation_gpio=int(relays["cwu_circulation_gpio"]),
            boiler_loading_gpio=int(relays["boiler_loading_gpio"]),
            electric_heater_gpio=int(relays["electric_heater_gpio"]),
            pellet_boiler_power_gpio=int(relays["pellet_boiler_power_gpio"]),
        ),
        automation=AutomationConfig(
            boiler_loading_temperature_c=float(
                automation["boiler_loading_temperature_c"]
            ),
            boiler_loading_seconds=int(automation["boiler_loading_seconds"]),
            boiler_loading_recheck_seconds=int(
                automation["boiler_loading_recheck_seconds"]
            ),
            pellet_low_level_percent=float(automation["pellet_low_level_percent"]),
            pellet_low_reminder_seconds=int(
                automation.get("pellet_low_reminder_seconds", 86400)
            ),
        ),
        scheduler=SchedulerConfig(
            enabled=bool(scheduler.get("enabled", True)),
            schedule_file=Path(str(scheduler.get("schedule_file", "runtime/schedule.json"))),
        ),
        manual_control=ManualControlConfig(
            enabled=bool(manual_control.get("enabled", True)),
            command_file=Path(
                str(manual_control.get("command_file", "runtime/manual_control.json"))
            ),
        ),
        history=HistoryConfig(
            enabled=bool(history.get("enabled", True)),
            database_file=Path(str(history.get("database_file", "runtime/history.db"))),
            sample_interval_seconds=float(history.get("sample_interval_seconds", 10.0)),
        ),
        email_notifications=EmailNotificationConfig(
            enabled=bool(email_notifications.get("enabled", False)),
            smtp_host=str(email_notifications.get("smtp_host", "")),
            smtp_port=int(email_notifications.get("smtp_port", 587)),
            use_starttls=bool(email_notifications.get("use_starttls", True)),
            username_env=str(
                email_notifications.get("username_env", "KOTLOWNIA_SMTP_USERNAME")
            ),
            password_env=str(
                email_notifications.get("password_env", "KOTLOWNIA_SMTP_PASSWORD")
            ),
            sender=str(email_notifications.get("sender", "")),
            recipient=str(email_notifications.get("recipient", "")),
        ),
    )
