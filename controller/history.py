from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from controller.events import ControllerEvent
from controller.state import ControllerState


class HistoryRepository:
    """Trwała historia pomiarów i zdarzeń w lokalnej bazie SQLite."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                pipe_temperature_c REAL,
                pellet_level_percent REAL,
                pellet_heating_detected INTEGER NOT NULL,
                pellet_low INTEGER NOT NULL,
                automation_state TEXT NOT NULL,
                automation_reason TEXT NOT NULL,
                cwu_circulation_on INTEGER NOT NULL,
                boiler_loading_on INTEGER NOT NULL,
                other_on INTEGER NOT NULL,
                pellet_boiler_power_on INTEGER NOT NULL,
                simulation_mode INTEGER NOT NULL,
                last_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_measurements_recorded_at
            ON measurements(recorded_at);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_occurred_at
            ON events(occurred_at);
            """
        )
        self._connection.commit()

        # Migracja starszej bazy po zmianie nazwy wyjścia z grzałki na "Inne".
        columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(measurements)").fetchall()
        }
        if "electric_heater_on" in columns and "other_on" not in columns:
            self._connection.execute(
                "ALTER TABLE measurements RENAME COLUMN electric_heater_on TO other_on"
            )
            self._connection.commit()

    def record_state(self, state: ControllerState) -> None:
        self._connection.execute(
            """
            INSERT INTO measurements (
                recorded_at,
                pipe_temperature_c,
                pellet_level_percent,
                pellet_heating_detected,
                pellet_low,
                automation_state,
                automation_reason,
                cwu_circulation_on,
                boiler_loading_on,
                other_on,
                pellet_boiler_power_on,
                simulation_mode,
                last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.updated_at,
                state.pipe_temperature_c,
                state.pellet_level_percent,
                int(state.pellet_heating_detected),
                int(state.pellet_low),
                state.automation_state,
                state.automation_reason,
                int(state.cwu_circulation_on),
                int(state.boiler_loading_on),
                int(state.other_on),
                int(state.pellet_boiler_power_on),
                int(state.simulation_mode),
                state.last_error,
            ),
        )
        self._connection.commit()

    def record_event(self, event: ControllerEvent) -> None:
        self._connection.execute(
            """
            INSERT INTO events (occurred_at, event_type, message, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.occurred_at,
                event.event_type.value,
                event.message,
                json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._connection.commit()

    def count_measurements(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM measurements"
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def count_events(self, event_type: str | None = None) -> int:
        if event_type is None:
            row = self._connection.execute("SELECT COUNT(*) FROM events").fetchone()
        else:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = ?",
                (event_type,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def latest_measurement(self) -> dict[str, Any] | None:
        cursor = self._connection.execute(
            """
            SELECT recorded_at, pipe_temperature_c, pellet_level_percent,
                   automation_state, last_error
            FROM measurements
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "recorded_at": row[0],
            "pipe_temperature_c": row[1],
            "pellet_level_percent": row[2],
            "automation_state": row[3],
            "last_error": row[4],
        }

    def close(self) -> None:
        self._connection.close()
