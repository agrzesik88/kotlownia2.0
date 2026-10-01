from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from controller.manual import ManualControlRepository


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value


def test_manual_control_activates_and_expires(tmp_path: Path) -> None:
    clock = Clock()
    repository = ManualControlRepository(tmp_path / "manual.json", now=clock.now)

    repository.activate("cwu_circulation", 10)
    assert repository.evaluate().cwu_circulation_requested is True

    clock.value += timedelta(minutes=11)
    decision = repository.evaluate()
    assert decision.cwu_circulation_requested is False
    assert decision.cwu_circulation_until is None


def test_manual_control_can_disable_one_output(tmp_path: Path) -> None:
    clock = Clock()
    repository = ManualControlRepository(tmp_path / "manual.json", now=clock.now)
    repository.activate("cwu_circulation", 10)
    repository.activate("other", 30)

    repository.deactivate("cwu_circulation")
    decision = repository.evaluate()
    assert decision.cwu_circulation_requested is False
    assert decision.other_requested is True


def test_manual_control_rejects_unsafe_duration(tmp_path: Path) -> None:
    repository = ManualControlRepository(tmp_path / "manual.json")
    with pytest.raises(ValueError):
        repository.activate("other", 121)


def test_manual_boiler_loading_disables_other_request(tmp_path: Path) -> None:
    clock = Clock()
    repository = ManualControlRepository(tmp_path / "manual.json", now=clock.now)
    repository.activate("other", 30)
    repository.activate("boiler_loading", 10)
    decision = repository.evaluate()
    assert decision.boiler_loading_requested is True
    assert decision.other_requested is False


def test_manual_power_override_can_force_off_and_expire(tmp_path: Path) -> None:
    clock = Clock()
    repository = ManualControlRepository(tmp_path / "manual.json", now=clock.now)
    repository.activate("pellet_boiler_power_off", 15)
    decision = repository.evaluate()
    assert decision.pellet_boiler_power_override is False
    clock.value += timedelta(minutes=16)
    assert repository.evaluate().pellet_boiler_power_override is None
