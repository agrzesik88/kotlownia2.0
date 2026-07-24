from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ControllerState:
    pipe_temperature_c: float | None = None
    pellet_level_percent: float | None = None

    cwu_circulation_on: bool = False
    boiler_loading_on: bool = False
    electric_heater_on: bool = False
    pellet_boiler_power_on: bool = True

    pellet_heating_detected: bool = False
    pellet_low: bool = False
    pellet_sensor_consecutive_failures: int = 0
    pellet_sensor_stale: bool = False
    scheduler_enabled: bool = False
    cwu_schedule_active: bool = False
    electric_heater_schedule_active: bool = False
    automation_state: str = "BOOT"
    automation_reason: str = ""
    simulation_mode: bool = True
    last_error: str | None = None
    updated_at: str = ""

    def update_timestamp(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
