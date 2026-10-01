from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SCHEDULE_TIMEZONE = "Europe/Warsaw"


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start: str
    end: str
    weekdays: tuple[str, ...] = WEEKDAYS
    duration_minutes: int = 10
    repeat_minutes: int = 60

    def __post_init__(self) -> None:
        start = _parse_time(self.start)
        end = _parse_time(self.end)
        invalid = set(self.weekdays) - set(WEEKDAYS)
        if invalid:
            raise ValueError(f"Nieprawidłowe dni tygodnia: {sorted(invalid)}")
        if not 1 <= self.duration_minutes <= 1440:
            raise ValueError("Czas trwania musi mieścić się w zakresie 1-1440 minut")
        if not 1 <= self.repeat_minutes <= 10080:
            raise ValueError("Ponowne uruchomienie musi mieścić się w zakresie 1-10080 minut")

        range_minutes = _range_minutes(start, end)
        if self.duration_minutes > range_minutes:
            raise ValueError(
                "Czas trwania nie może być dłuższy niż zakres harmonogramu"
            )
        if self.repeat_minutes < self.duration_minutes:
            raise ValueError(
                "Ponowne uruchomienie nie może być krótsze niż czas trwania"
            )

    def matches(self, local_datetime: datetime) -> bool:
        day = WEEKDAYS[local_datetime.weekday()]
        current = local_datetime.timetz().replace(tzinfo=None)
        start = _parse_time(self.start)
        end = _parse_time(self.end)

        if start == end:
            if day not in self.weekdays:
                return False
            elapsed_minutes = current.hour * 60 + current.minute
            return elapsed_minutes % self.repeat_minutes < self.duration_minutes

        if start < end:
            if day not in self.weekdays:
                return False
            elapsed_minutes = _minutes_since(start, current)
            range_minutes = _range_minutes(start, end)
            if not 0 <= elapsed_minutes < range_minutes:
                return False
            return elapsed_minutes % self.repeat_minutes < self.duration_minutes

        # Zakres przechodzący przez północ, np. 22:00-06:00.
        if current >= start:
            if day not in self.weekdays:
                return False
            elapsed_minutes = _minutes_since(start, current)
        else:
            previous_day = WEEKDAYS[(local_datetime.weekday() - 1) % 7]
            if previous_day not in self.weekdays:
                return False
            elapsed_minutes = _minutes_since(start, current, wrap=True)

        range_minutes = _range_minutes(start, end)
        if not 0 <= elapsed_minutes < range_minutes:
            return False
        return elapsed_minutes % self.repeat_minutes < self.duration_minutes


@dataclass(frozen=True, slots=True)
class OutputSchedule:
    enabled: bool = False
    windows: tuple[TimeWindow, ...] = ()

    def active_at(self, local_datetime: datetime) -> bool:
        return self.enabled and any(window.matches(local_datetime) for window in self.windows)


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    timezone: str = SCHEDULE_TIMEZONE
    cwu_circulation: OutputSchedule = field(default_factory=OutputSchedule)
    other: OutputSchedule = field(default_factory=OutputSchedule)

    def __post_init__(self) -> None:
        ZoneInfo(SCHEDULE_TIMEZONE)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("timezone", None)
        return data


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    cwu_circulation_requested: bool
    other_requested: bool


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
        zone = ZoneInfo(SCHEDULE_TIMEZONE)
        local_now = now.astimezone(zone) if now is not None else datetime.now(zone)
        return ScheduleDecision(
            cwu_circulation_requested=self._config.cwu_circulation.active_at(local_now),
            other_requested=self._config.other.active_at(local_now),
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
                raise ValueError("Zakres harmonogramu musi być obiektem")
            weekdays_raw = item.get("weekdays", WEEKDAYS)
            if not isinstance(weekdays_raw, list | tuple):
                raise ValueError("weekdays musi być listą")
            windows.append(
                TimeWindow(
                    start=str(item["start"]),
                    end=str(item["end"]),
                    weekdays=tuple(str(day) for day in weekdays_raw),
                    duration_minutes=int(item.get("duration_minutes", 10)),
                    repeat_minutes=int(item.get("repeat_minutes", 60)),
                )
            )
        return OutputSchedule(
            enabled=bool(value.get("enabled", False)),
            windows=tuple(windows),
        )

    return ScheduleConfig(
        timezone=SCHEDULE_TIMEZONE,
        cwu_circulation=output("cwu_circulation"),
        other=output("other"),
    )


def _parse_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Nieprawidłowa godzina: {value}") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError("Harmonogram obsługuje dokładność do minuty")
    return parsed


def _range_minutes(start: time, end: time) -> int:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if start == end:
        return 24 * 60
    return (end_minutes - start_minutes) % (24 * 60)


def _minutes_since(start: time, current: time, wrap: bool = False) -> int:
    start_minutes = start.hour * 60 + start.minute
    current_minutes = current.hour * 60 + current.minute
    elapsed = current_minutes - start_minutes
    if wrap and elapsed < 0:
        elapsed += 24 * 60
    return elapsed
