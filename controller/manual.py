from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class ManualControlState:
    cwu_circulation_until: str | None = None
    other_until: str | None = None
    boiler_loading_until: str | None = None
    pellet_boiler_power_override: bool | None = None
    pellet_boiler_power_until: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
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
    """Atomowy plik poleceń współdzielony przez API i proces sterownika."""

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
        power_override = raw.get("pellet_boiler_power_override")
        if power_override is not None and not isinstance(power_override, bool):
            raise ValueError("Wymuszenie zasilania pieca musi być wartością logiczną")
        return ManualControlState(
            cwu_circulation_until=self._validate_timestamp(raw.get("cwu_circulation_until")),
            other_until=self._validate_timestamp(raw.get("other_until")),
            boiler_loading_until=self._validate_timestamp(raw.get("boiler_loading_until")),
            pellet_boiler_power_override=power_override,
            pellet_boiler_power_until=self._validate_timestamp(raw.get("pellet_boiler_power_until")),
        )

    def evaluate(self) -> ManualControlDecision:
        state = self.load()
        now = self._ensure_utc(self._now())
        cwu_active = self._is_active(state.cwu_circulation_until, now)
        other_active = self._is_active(state.other_until, now)
        loading_active = self._is_active(state.boiler_loading_until, now)
        power_active = self._is_active(state.pellet_boiler_power_until, now)
        cleaned = ManualControlState(
            cwu_circulation_until=state.cwu_circulation_until if cwu_active else None,
            other_until=state.other_until if other_active else None,
            boiler_loading_until=state.boiler_loading_until if loading_active else None,
            pellet_boiler_power_override=(state.pellet_boiler_power_override if power_active else None),
            pellet_boiler_power_until=state.pellet_boiler_power_until if power_active else None,
        )
        if cleaned != state:
            self.save(cleaned)
        return ManualControlDecision(
            cwu_circulation_requested=cwu_active,
            other_requested=other_active,
            boiler_loading_requested=loading_active,
            pellet_boiler_power_override=cleaned.pellet_boiler_power_override,
            cwu_circulation_until=cleaned.cwu_circulation_until,
            other_until=cleaned.other_until,
            boiler_loading_until=cleaned.boiler_loading_until,
            pellet_boiler_power_until=cleaned.pellet_boiler_power_until,
        )

    def activate(self, output: str, duration_minutes: int) -> ManualControlState:
        limits = {
            "cwu_circulation": (1, 60),
            "other": (1, 120),
            "boiler_loading": (1, 60),
            "pellet_boiler_power_on": (1, 240),
            "pellet_boiler_power_off": (1, 240),
        }
        if output not in limits:
            raise ValueError("Nieobsługiwane wyjście sterowania ręcznego")
        minimum, maximum = limits[output]
        if not minimum <= duration_minutes <= maximum:
            raise ValueError(f"Czas musi mieścić się w zakresie {minimum}-{maximum} minut")
        state = self.load()
        expires_at = (self._ensure_utc(self._now()) + timedelta(minutes=duration_minutes)).isoformat()
        values = state.to_dict()
        if output == "cwu_circulation":
            values["cwu_circulation_until"] = expires_at
        elif output == "other":
            values["other_until"] = expires_at
            values["boiler_loading_until"] = None
        elif output == "boiler_loading":
            values["boiler_loading_until"] = expires_at
            values["other_until"] = None
        else:
            values["pellet_boiler_power_override"] = output.endswith("_on")
            values["pellet_boiler_power_until"] = expires_at
        new_state = ManualControlState(**values)
        self.save(new_state)
        return new_state

    def deactivate(self, output: str) -> ManualControlState:
        state = self.load()
        values = state.to_dict()
        if output == "cwu_circulation":
            values["cwu_circulation_until"] = None
        elif output == "other":
            values["other_until"] = None
        elif output == "boiler_loading":
            values["boiler_loading_until"] = None
        elif output == "pellet_boiler_power":
            values["pellet_boiler_power_override"] = None
            values["pellet_boiler_power_until"] = None
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
        temporary.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _validate_timestamp(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Czas wygaśnięcia musi być tekstem ISO-8601")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("Czas wygaśnięcia musi zawierać strefę czasową")
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _is_active(value: str | None, now: datetime) -> bool:
        return value is not None and datetime.fromisoformat(value) > now

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Zegar musi zwracać czas ze strefą czasową")
        return value.astimezone(timezone.utc)
