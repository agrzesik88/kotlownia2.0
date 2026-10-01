from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class ManualControlState:
    cwu_circulation_active: bool = False
    other_active: bool = False
    boiler_loading_active: bool = False
    pellet_boiler_power_override: bool | None = None

    def to_dict(self) -> dict[str, bool | None]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ManualControlDecision:
    cwu_circulation_requested: bool = False
    other_requested: bool = False
    boiler_loading_requested: bool = False
    pellet_boiler_power_override: bool | None = None
    cwu_circulation_until: str | None = None
    other_until: str | None = None
    boiler_loading_until: str | None = None
    pellet_boiler_power_until: str | None = None


class ManualControlRepository:
    """Atomowy plik trwałych poleceń współdzielony przez API i proces sterownika."""

    def __init__(self, path: str | Path, *, now: Callable[[], datetime] | None = None) -> None:
        self.path = Path(path)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def load(self) -> ManualControlState:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ManualControlState()
        except json.JSONDecodeError as exc:
            raise ValueError("Nieprawidłowy plik sterowania ręcznego") from exc
        if not isinstance(raw, dict):
            raise ValueError("Nieprawidłowy format sterowania ręcznego")

        # Migracja starego formatu z czasem wygaśnięcia.
        if any(key in raw for key in ("cwu_circulation_until", "other_until", "boiler_loading_until")):
            now = self._ensure_utc(self._now())
            return ManualControlState(
                cwu_circulation_active=self._legacy_active(raw.get("cwu_circulation_until"), now),
                other_active=self._legacy_active(raw.get("other_until"), now),
                boiler_loading_active=self._legacy_active(raw.get("boiler_loading_until"), now),
                pellet_boiler_power_override=self._legacy_power_active(raw, now),
            )

        power_override = raw.get("pellet_boiler_power_override")
        if power_override is not None and not isinstance(power_override, bool):
            raise ValueError("Wymuszenie zasilania pieca musi być wartością logiczną")

        return ManualControlState(
            cwu_circulation_active=bool(raw.get("cwu_circulation_active", False)),
            other_active=bool(raw.get("other_active", False)),
            boiler_loading_active=bool(raw.get("boiler_loading_active", False)),
            pellet_boiler_power_override=power_override,
        )

    def evaluate(self) -> ManualControlDecision:
        state = self.load()
        return ManualControlDecision(
            cwu_circulation_requested=state.cwu_circulation_active,
            other_requested=state.other_active,
            boiler_loading_requested=state.boiler_loading_active,
            pellet_boiler_power_override=state.pellet_boiler_power_override,
            cwu_circulation_until=None,
            other_until=None,
            boiler_loading_until=None,
            pellet_boiler_power_until=None,
        )

    def activate(self, output: str, duration_minutes: int | None = None) -> ManualControlState:
        if output not in {
            "cwu_circulation",
            "other",
            "boiler_loading",
            "pellet_boiler_power_on",
            "pellet_boiler_power_off",
        }:
            raise ValueError("Nieobsługiwane wyjście sterowania ręcznego")

        state = self.load()
        values = state.to_dict()
        if output == "cwu_circulation":
            values["cwu_circulation_active"] = True
        elif output == "other":
            values["other_active"] = True
        elif output == "boiler_loading":
            values["boiler_loading_active"] = True
        else:
            values["pellet_boiler_power_override"] = output.endswith("_on")

        new_state = ManualControlState(**values)
        self.save(new_state)
        return new_state

    def deactivate(self, output: str) -> ManualControlState:
        state = self.load()
        values = state.to_dict()
        if output == "cwu_circulation":
            values["cwu_circulation_active"] = False
        elif output == "other":
            values["other_active"] = False
        elif output == "boiler_loading":
            values["boiler_loading_active"] = False
        elif output == "pellet_boiler_power":
            values["pellet_boiler_power_override"] = None
        else:
            raise ValueError("Nieobsługiwane wyjście sterowania ręcznego")
        new_state = ManualControlState(**values)
        self.save(new_state)
        return new_state

    def clear(self) -> ManualControlState:
        state = ManualControlState()
        self.save(state)
        return state

    def save(self, state: ManualControlState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _legacy_active(value: object, now: datetime) -> bool:
        if value is None:
            return False
        if not isinstance(value, str):
            raise ValueError("Czas wygaśnięcia musi być tekstem ISO-8601")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("Czas wygaśnięcia musi zawierać strefę czasową")
        return parsed.astimezone(timezone.utc) > now

    @classmethod
    def _legacy_power_active(cls, raw: dict[str, object], now: datetime) -> bool | None:
        override = raw.get("pellet_boiler_power_override")
        if override is not None and not isinstance(override, bool):
            raise ValueError("Wymuszenie zasilania pieca musi być wartością logiczną")
        if not cls._legacy_active(raw.get("pellet_boiler_power_until"), now):
            return None
        return override

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Zegar musi zwracać czas ze strefą czasową")
        return value.astimezone(timezone.utc)
