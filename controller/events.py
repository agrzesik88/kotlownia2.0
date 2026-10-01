from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class EventType(str, Enum):
    PELLET_LOW = "PELLET_LOW"
    PELLET_RECOVERED = "PELLET_RECOVERED"
    CONTROLLER_ERROR = "CONTROLLER_ERROR"
    CONTROLLER_RECOVERED = "CONTROLLER_RECOVERED"
    CWU_CIRCULATION_SCHEDULE_STARTED = "CWU_CIRCULATION_SCHEDULE_STARTED"


@dataclass(frozen=True, slots=True)
class ControllerEvent:
    event_type: EventType
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


EventHandler = Callable[[ControllerEvent], None]


class EventBus:
    """Synchroniczny, lokalny mechanizm zdarzeń bez zależności od sieci."""

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        if handler not in self._handlers:
            self._handlers.append(handler)

    def publish(self, event: ControllerEvent) -> None:
        for handler in tuple(self._handlers):
            handler(event)
