from datetime import datetime, timezone
from pathlib import Path

from controller.manual import ManualControlRepository


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value


def test_manual_control_stays_active_until_explicitly_disabled(tmp_path: Path) -> None:
    clock = Clock()
    repository = ManualControlRepository(tmp_path / "manual.json", now=clock.now)

    repository.activate("cwu_circulation")
    assert repository.evaluate().cwu_circulation_requested is True

    clock.value = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert repository.evaluate().cwu_circulation_requested is True

    repository.deactivate("cwu_circulation")
    assert repository.evaluate().cwu_circulation_requested is False


def test_manual_control_can_disable_one_output(tmp_path: Path) -> None:
    clock = Clock()
    repository = ManualControlRepository(tmp_path / "manual.json", now=clock.now)
    repository.activate("cwu_circulation")
    repository.activate("other")

    repository.deactivate("cwu_circulation")
    decision = repository.evaluate()
    assert decision.cwu_circulation_requested is False
    assert decision.other_requested is True



def test_manual_boiler_loading_does_not_disable_other_request(tmp_path: Path) -> None:
    clock = Clock()
    repository = ManualControlRepository(tmp_path / "manual.json", now=clock.now)
    repository.activate("other", 30)
    repository.activate("boiler_loading")
    decision = repository.evaluate()
    assert decision.boiler_loading_requested is True
    assert decision.other_requested is True


def test_manual_power_override_stays_active_until_explicitly_disabled(tmp_path: Path) -> None:
    repository = ManualControlRepository(tmp_path / "manual.json")
    repository.activate("pellet_boiler_power_off")
    assert repository.evaluate().pellet_boiler_power_override is False

    repository.deactivate("pellet_boiler_power")
    assert repository.evaluate().pellet_boiler_power_override is None
