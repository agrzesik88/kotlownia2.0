from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start: str
    end: str
    weekdays: tuple[str, ...] = WEEKDAYS

    def __post_init__(self) -> None:
        _parse_time(self.start)
        _parse_time(self.end)
        invalid = set(self.weekdays) - set(WEEKDAYS)
        if invalid:
            raise ValueError(f"Nieprawidłowe dni tygodnia: {sorted(invalid)}")

    def matches(self, local_datetime: datetime) -> bool:
        day = WEEKDAYS[local_datetime.weekday()]
        current = local_datetime.timetz().replace(tzinfo=None)
        start = _parse_time(self.start)
        end = _parse_time(self.end)

        if start == end:
            return day in self.weekdays
        if start < end:
            return day in self.weekdays and start <= current < end

        # Okno przechodzące przez północ, np. 22:00-06:00. Część po
        # północy należy do dnia, w którym okno się rozpoczęło.
        if current >= start:
            return day in self.weekdays
        previous_day = WEEKDAYS[(local_datetime.weekday() - 1) % 7]
        return previous_day in self.weekdays and current < end


@dataclass(frozen=True, slots=True)
class OutputSchedule:
    enabled: bool = False
    windows: tuple[TimeWindow, ...] = ()

    def active_at(self, local_datetime: datetime) -> bool:
        return self.enabled and any(window.matches(local_datetime) for window in self.windows)


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    timezone: str = "Europe/Warsaw"
    cwu_circulation: OutputSchedule = field(default_factory=OutputSchedule)
    electric_heater: OutputSchedule = field(default_factory=OutputSchedule)

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    cwu_circulation_requested: bool
    electric_heater_requested: bool


class ScheduleRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> ScheduleConfig:
        if not self.path.exists():
            config = ScheduleConfig()
            self.save(config)
            return config
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Plik harmonogramu musi zawierać obiekt JSON")
        return schedule_from_dict(raw)

    def save(self, config: ScheduleConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class TimeScheduler:
    def __init__(self, repository: ScheduleRepository) -> None:
        self.repository = repository
        self._config = repository.load()

    @property
    def config(self) -> ScheduleConfig:
        return self._config

    def evaluate(self, now: datetime | None = None) -> ScheduleDecision:
        self._config = self.repository.load()
        zone = ZoneInfo(self._config.timezone)
        local_now = now.astimezone(zone) if now is not None else datetime.now(zone)
        return ScheduleDecision(
            cwu_circulation_requested=self._config.cwu_circulation.active_at(local_now),
            electric_heater_requested=self._config.electric_heater.active_at(local_now),
        )

def schedule_from_dict(raw: dict[str, Any]) -> ScheduleConfig:
    def output(name: str) -> OutputSchedule:
        value = raw.get(name, {})
        if not isinstance(value, dict):
            raise ValueError(f"Sekcja {name} musi być obiektem")
        windows_raw = value.get("windows", [])
        if not isinstance(windows_raw, list):
            raise ValueError(f"{name}.windows musi być listą")
        windows: list[TimeWindow] = []
        for item in windows_raw:
            if not isinstance(item, dict):
                raise ValueError("Okno harmonogramu musi być obiektem")
            weekdays_raw = item.get("weekdays", WEEKDAYS)
            if not isinstance(weekdays_raw, list | tuple):
                raise ValueError("weekdays musi być listą")
            windows.append(
                TimeWindow(
                    start=str(item["start"]),
                    end=str(item["end"]),
                    weekdays=tuple(str(day) for day in weekdays_raw),
                )
            )
        return OutputSchedule(
            enabled=bool(value.get("enabled", False)),
            windows=tuple(windows),
        )

    return ScheduleConfig(
        timezone=str(raw.get("timezone", "Europe/Warsaw")),
        cwu_circulation=output("cwu_circulation"),
        electric_heater=output("electric_heater"),
    )


def _parse_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Nieprawidłowa godzina: {value}") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError("Harmonogram obsługuje dokładność do minuty")
    return parsed
