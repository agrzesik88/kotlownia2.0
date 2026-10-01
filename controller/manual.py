from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class ManualControlState:
    cwu_circulation_active: bool = False
    cwu_circulation_until: str | None = None
    other_active: bool = False
    other_until: str | None = None
    boiler_loading_active: bool = False
    boiler_loading_until: str | None = None
    pellet_boiler_power_override: bool | None = None

    def to_dict(self) -> dict[str, bool | str | None]:
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

        now = self._ensure_utc(self._now())
        if any(key in raw for key in ("cwu_circulation_until", "other_until", "boiler_loading_until")):
            return ManualControlState(
                cwu_circulation_active=bool(raw.get("cwu_circulation_active", False)),
                cwu_circulation_until=self._legacy_timestamp(raw.get("cwu_circulation_until"), now),
                other_active=bool(raw.get("other_active", False)),
                other_until=self._legacy_timestamp(raw.get("other_until"), now),
                boiler_loading_active=bool(raw.get("boiler_loading_active", False)),
                boiler_loading_until=self._legacy_timestamp(raw.get("boiler_loading_until"), now),
                pellet_boiler_power_override=self._legacy_power(raw, now),
            )

        power_override = raw.get("pellet_boiler_power_override")
        if power_override is not None and not isinstance(power_override, bool):
            raise ValueError("Wymuszenie zasilania pieca musi być wartością logiczną")

        return ManualControlState(
            cwu_circulation_active=bool(raw.get("cwu_circulation_active", False)),
            cwu_circulation_until=self._validate_timestamp(raw.get("cwu_circulation_until"), now),
            other_active=bool(raw.get("other_active", False)),
            other_until=self._validate_timestamp(raw.get("other_until"), now),
            boiler_loading_active=bool(raw.get("boiler_loading_active", False)),
            boiler_loading_until=self._validate_timestamp(raw.get("boiler_loading_until"), now),
            pellet_boiler_power_override=power_override,
        )

    def evaluate(self) -> ManualControlDecision:
        state = self.load()
        now = self._ensure_utc(self._now())
        cwu_timed = self._is_active(state.cwu_circulation_until, now)
        other_timed = self._is_active(state.other_until, now)
        boiler_timed = self._is_active(state.boiler_loading_until, now)
        return ManualControlDecision(
            cwu_circulation_requested=state.cwu_circulation_active or cwu_timed,
            other_requested=state.other_active or other_timed,
            boiler_loading_requested=state.boiler_loading_active or boiler_timed,
            pellet_boiler_power_override=state.pellet_boiler_power_override,
            cwu_circulation_until=state.cwu_circulation_until if cwu_timed else None,
            other_until=state.other_until if other_timed else None,
            boiler_loading_until=state.boiler_loading_until if boiler_timed else None,
            pellet_boiler_power_until=None,
        )

    def activate(self, output: str, duration_minutes: int | None = None) -> ManualControlState:
        allowed = {"cwu_circulation", "other", "boiler_loading", "pellet_boiler_power_on", "pellet_boiler_power_off"}
        if output not in allowed:
            raise ValueError("Nieobsługiwane wyjście sterowania ręcznego")
        if duration_minutes is not None and duration_minutes < 1:
            raise ValueError("Czas musi być większy od 0 minut")

        state = self.load()
        values = state.to_dict()
        expires_at = (
            self._ensure_utc(self._now()) + timedelta(minutes=duration_minutes)
        ).isoformat() if duration_minutes is not None else None

        if output == "cwu_circulation":
            values["cwu_circulation_active"] = duration_minutes is None
            values["cwu_circulation_until"] = expires_at
        elif output == "other":
            values["other_active"] = duration_minutes is None
            values["other_until"] = expires_at
        elif output == "boiler_loading":
            values["boiler_loading_active"] = duration_minutes is None
            values["boiler_loading_until"] = expires_at
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
            values["cwu_circulation_until"] = None
        elif output == "other":
            values["other_active"] = False
            values["other_until"] = None
        elif output == "boiler_loading":
            values["boiler_loading_active"] = False
            values["boiler_loading_until"] = None
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
        temporary.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @classmethod
    def _validate_timestamp(cls, value: object, now: datetime) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Czas wygaśnięcia musi być tekstem ISO-8601")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("Czas wygaśnięcia musi zawierać strefę czasową")
        return parsed.astimezone(timezone.utc).isoformat() if parsed.astimezone(timezone.utc) > now else None

    @classmethod
    def _legacy_timestamp(cls, value: object, now: datetime) -> str | None:
        return cls._validate_timestamp(value, now)

    @classmethod
    def _legacy_power(cls, raw: dict[str, object], now: datetime) -> bool | None:
        override = raw.get("pellet_boiler_power_override")
        if override is not None and not isinstance(override, bool):
            raise ValueError("Wymuszenie zasilania pieca musi być wartością logiczną")
        return override

    @staticmethod
    def _is_active(value: str | None, now: datetime) -> bool:
        return value is not None and datetime.fromisoformat(value) > now

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Zegar musi zwracać czas ze strefą czasową")
        return value.astimezone(timezone.utc)
