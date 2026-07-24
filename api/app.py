from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from controller.config import ControllerConfig, load_config
from controller.scheduler import ScheduleRepository, schedule_from_dict


class SchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str
    cwu_circulation: dict[str, Any]
    electric_heater: dict[str, Any]


def create_app(config_path: str | Path = "config/settings.toml") -> FastAPI:
    config = load_config(config_path)
    app = FastAPI(title="Kotłownia 2.0", version="0.3.0")
    app.state.controller_config = config
    app.state.schedule_repository = ScheduleRepository(config.scheduler.schedule_file)

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return _read_state(config)

    @app.get("/api/history")
    def history(limit: int = 120) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise HTTPException(400, "limit musi mieścić się w zakresie 1-1000")
        return _read_history(config, limit)

    @app.get("/api/events")
    def events(limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise HTTPException(400, "limit musi mieścić się w zakresie 1-500")
        return _read_events(config, limit)

    @app.get("/api/schedule")
    def get_schedule() -> dict[str, Any]:
        return app.state.schedule_repository.load().to_dict()

    @app.put("/api/schedule")
    def put_schedule(payload: SchedulePayload) -> dict[str, Any]:
        try:
            schedule = schedule_from_dict(payload.model_dump())
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        app.state.schedule_repository.save(schedule)
        return schedule.to_dict()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _read_state(config: ControllerConfig) -> dict[str, Any]:
    try:
        raw = json.loads(config.application.state_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(503, "Sterownik nie zapisał jeszcze stanu") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(503, "Plik stanu jest chwilowo nieczytelny") from exc
    if not isinstance(raw, dict):
        raise HTTPException(503, "Nieprawidłowy format stanu")
    return raw


def _read_history(config: ControllerConfig, limit: int) -> list[dict[str, Any]]:
    if not config.history.database_file.exists():
        return []
    with sqlite3.connect(config.history.database_file, timeout=2.0) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT recorded_at, pipe_temperature_c, pellet_level_percent,
                   automation_state, cwu_circulation_on, boiler_loading_on,
                   electric_heater_on, pellet_boiler_power_on, last_error
            FROM measurements
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def _read_events(config: ControllerConfig, limit: int) -> list[dict[str, Any]]:
    if not config.history.database_file.exists():
        return []
    with sqlite3.connect(config.history.database_file, timeout=2.0) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT occurred_at, event_type, message, payload_json
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result

