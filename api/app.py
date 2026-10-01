from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from controller.config import ControllerConfig, load_config
from controller.manual import ManualControlRepository
from controller.scheduler import ScheduleRepository, schedule_from_dict


class ManualControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: str
    duration_minutes: int


class AutomationSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boiler_loading_temperature_c: float = Field(ge=-55.0, le=125.0)
    boiler_loading_minutes: int = Field(gt=0, le=1440)
    boiler_loading_recheck_minutes: int = Field(gt=0, le=10080)
    pellet_low_level_percent: float = Field(ge=0.0, le=100.0)


class SchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str
    cwu_circulation: dict[str, Any]
    other: dict[str, Any]


def create_app(config_path: str | Path = "config/settings.toml") -> FastAPI:
    config = load_config(config_path)
    app = FastAPI(title="Kotłownia 2.0", version="0.4.1")
    app.state.controller_config = config
    app.state.schedule_repository = ScheduleRepository(config.scheduler.schedule_file)
    app.state.manual_repository = ManualControlRepository(
        config.manual_control.command_file
    )

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return _read_state(config)

    @app.get("/api/automation-status")
    def automation_status() -> dict[str, Any]:
        state = _read_state(config)
        return {
            "automation_state": state.get("automation_state", "BOOT"),
            "automation_reason": state.get("automation_reason", ""),
            "outputs": state.get("output_status", {}),
            "updated_at": state.get("updated_at", ""),
        }

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

    @app.get("/api/automation-settings")
    def get_automation_settings() -> dict[str, Any]:
        return _read_automation_settings(config)

    @app.put("/api/automation-settings")
    def put_automation_settings(payload: AutomationSettingsPayload) -> dict[str, Any]:
        path = config.application.state_file.parent / "automation_settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = payload.model_dump()
        runtime_data = {
            "boiler_loading_temperature_c": data["boiler_loading_temperature_c"],
            "boiler_loading_seconds": data["boiler_loading_minutes"] * 60,
            "boiler_loading_recheck_seconds": data["boiler_loading_recheck_minutes"] * 60,
            "pellet_low_level_percent": data["pellet_low_level_percent"],
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(runtime_data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return data

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


    @app.get("/api/manual")
    def get_manual() -> dict[str, Any]:
        decision = app.state.manual_repository.evaluate()
        return {
            "cwu_circulation_active": decision.cwu_circulation_requested,
            "other_active": decision.other_requested,
            "boiler_loading_active": decision.boiler_loading_requested,
            "pellet_boiler_power_override": decision.pellet_boiler_power_override,
            "cwu_circulation_until": decision.cwu_circulation_until,
            "other_until": decision.other_until,
            "boiler_loading_until": decision.boiler_loading_until,
            "pellet_boiler_power_until": decision.pellet_boiler_power_until,
        }

    @app.post("/api/manual/activate")
    def activate_manual(payload: ManualControlPayload) -> dict[str, Any]:
        if not config.manual_control.enabled:
            raise HTTPException(409, "Sterowanie ręczne jest wyłączone")
        try:
            state = app.state.manual_repository.activate(
                payload.output, payload.duration_minutes
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return state.to_dict()

    @app.post("/api/manual/deactivate/{output}")
    def deactivate_manual(output: str) -> dict[str, Any]:
        try:
            state = app.state.manual_repository.deactivate(output)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return state.to_dict()

    @app.post("/api/manual/clear")
    def clear_manual() -> dict[str, Any]:
        return app.state.manual_repository.clear().to_dict()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _read_automation_settings(config: ControllerConfig) -> dict[str, Any]:
    defaults = {
        "boiler_loading_temperature_c": config.automation.boiler_loading_temperature_c,
        "boiler_loading_minutes": config.automation.boiler_loading_seconds // 60,
        "boiler_loading_recheck_minutes": config.automation.boiler_loading_recheck_seconds // 60,
        "pellet_low_level_percent": config.automation.pellet_low_level_percent,
    }
    path = config.application.state_file.parent / "automation_settings.json"
    if not path.is_file():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    try:
        return AutomationSettingsPayload.model_validate({
            "boiler_loading_temperature_c": raw["boiler_loading_temperature_c"],
            "boiler_loading_minutes": int(raw["boiler_loading_seconds"]) // 60,
            "boiler_loading_recheck_minutes": int(raw["boiler_loading_recheck_seconds"]) // 60,
            "pellet_low_level_percent": raw["pellet_low_level_percent"],
        }).model_dump()
    except Exception:
        return defaults


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
                   other_on, pellet_boiler_power_on, last_error
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

