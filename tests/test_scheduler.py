from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from controller.scheduler import (
    OutputSchedule,
    ScheduleConfig,
    ScheduleRepository,
    TimeScheduler,
    TimeWindow,
)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Europe/Warsaw"))


def test_time_window_matches_selected_weekday() -> None:
    window = TimeWindow("06:00", "06:10", ("mon", "wed"))
    assert window.matches(dt("2026-07-20T06:05"))
    assert not window.matches(dt("2026-07-21T06:05"))
    assert not window.matches(dt("2026-07-20T06:10"))


def test_window_crossing_midnight_uses_start_day() -> None:
    window = TimeWindow("22:00", "06:00", ("fri",))
    assert window.matches(dt("2026-07-24T23:00"))
    assert window.matches(dt("2026-07-25T05:30"))
    assert not window.matches(dt("2026-07-26T05:30"))


def test_scheduler_reloads_changed_file(tmp_path: Path) -> None:
    repository = ScheduleRepository(tmp_path / "schedule.json")
    repository.save(ScheduleConfig())
    scheduler = TimeScheduler(repository)
    assert not scheduler.evaluate(dt("2026-07-20T06:05")).cwu_circulation_requested

    repository.save(
        ScheduleConfig(
            cwu_circulation=OutputSchedule(
                enabled=True,
                windows=(TimeWindow("06:00", "06:10", ("mon",)),),
            )
        )
    )
    assert scheduler.evaluate(dt("2026-07-20T06:05")).cwu_circulation_requested


def test_invalid_time_is_rejected() -> None:
    try:
        TimeWindow("25:00", "06:00")
    except ValueError as exc:
        assert "Nieprawidłowa godzina" in str(exc)
    else:
        raise AssertionError("Nieprawidłowa godzina powinna zostać odrzucona")

def test_range_runs_for_duration_and_repeats() -> None:
    window = TimeWindow(
        "06:00",
        "08:00",
        ("mon",),
        duration_minutes=10,
        repeat_minutes=60,
    )
    assert window.matches(dt("2026-07-20T06:00"))
    assert window.matches(dt("2026-07-20T06:09"))
    assert not window.matches(dt("2026-07-20T06:10"))
    assert window.matches(dt("2026-07-20T07:00"))
    assert not window.matches(dt("2026-07-20T07:10"))
    assert not window.matches(dt("2026-07-20T08:00"))


def test_overnight_range_repeats_after_midnight() -> None:
    window = TimeWindow(
        "22:00",
        "06:00",
        ("fri",),
        duration_minutes=10,
        repeat_minutes=60,
    )
    assert window.matches(dt("2026-07-24T22:00"))
    assert window.matches(dt("2026-07-25T00:00"))
    assert not window.matches(dt("2026-07-25T00:10"))
    assert not window.matches(dt("2026-07-25T06:00"))


def test_duration_cannot_exceed_range() -> None:
    try:
        TimeWindow("06:00", "07:00", ("mon",), duration_minutes=61, repeat_minutes=60)
    except ValueError as exc:
        assert "dłuższy niż zakres" in str(exc)
    else:
        raise AssertionError("Czas trwania nie może przekraczać zakresu")
