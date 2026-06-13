from __future__ import annotations

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, save_dispatch_data
from cairn.server.models_pkg.common import Settings
from cairn.shared.contracts import TaskTimeouts


def get_yaml_settings() -> Settings:
    data = load_dispatch_data()
    server_raw = data.get("server")
    server = server_raw if isinstance(server_raw, dict) else {}
    settings_raw = server.get("settings")
    server_settings = settings_raw if isinstance(settings_raw, dict) else {}
    missing = [key for key in ("intent_timeout", "reason_timeout") if key not in server_settings]
    if missing:
        raise HTTPException(500, f"dispatch.yaml server.settings missing required fields: {', '.join(missing)}")
    return Settings(
        intent_timeout=int(server_settings["intent_timeout"]),
        reason_timeout=int(server_settings["reason_timeout"]),
    )


def update_yaml_settings(body: Settings) -> Settings:
    data = load_dispatch_data()
    server = data.setdefault("server", {})
    if not isinstance(server, dict):
        raise HTTPException(500, "dispatch.yaml server must be a mapping")
    server["settings"] = {
        "intent_timeout": body.intent_timeout,
        "reason_timeout": body.reason_timeout,
    }
    save_dispatch_data(data)
    return body


def get_yaml_task_timeouts() -> TaskTimeouts:
    data = load_dispatch_data()
    tasks_raw = data.get("tasks")
    tasks = tasks_raw if isinstance(tasks_raw, dict) else {}
    try:
        return TaskTimeouts.model_validate(
            {
                "bootstrap": {
                    "timeout": tasks["bootstrap"]["timeout"],
                    "conclude_timeout": tasks["bootstrap"]["conclude_timeout"],
                },
                "explore": {
                    "timeout": tasks["explore"]["timeout"],
                    "conclude_timeout": tasks["explore"]["conclude_timeout"],
                },
                "reason": {
                    "timeout": tasks["reason"]["timeout"],
                },
            }
        )
    except Exception as exc:
        raise HTTPException(500, f"dispatch.yaml tasks missing or invalid timeout fields: {exc}") from exc
