from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, save_dispatch_data
from cairn.shared.contracts.observability import ObservabilitySettings
from cairn.shared.contracts.runtime_limits import RuntimeLimits
from cairn.shared.contracts.settings import Settings
from cairn.shared.contracts.system_config import ServerLogRetention, SystemSettingsAdmin
from cairn.shared.contracts.timeouts import (
    BootstrapTaskTimeouts,
    ExploreTaskTimeouts,
    ReasonTaskTimeouts,
    TaskTimeouts,
)


def get_system_settings() -> SystemSettingsAdmin:
    data = load_dispatch_data()
    return _system_settings_from_data(data)


def update_system_settings(body: SystemSettingsAdmin) -> SystemSettingsAdmin:
    if body.runtime_limits.max_project_workers > body.runtime_limits.max_workers:
        raise HTTPException(400, "max_project_workers cannot exceed max_workers")

    data = load_dispatch_data()
    _write_settings(data, body.settings)
    _write_runtime_limits(data, body.runtime_limits)
    _write_task_timeouts(data, body.task_timeouts)
    _write_observability(data, body.observability)
    _write_server_log_retention(data, body.server_log_retention)
    reload_status = save_dispatch_data(data)
    result = _system_settings_from_data(data)
    return result.model_copy(update=reload_status)


def _system_settings_from_data(data: dict[str, Any]) -> SystemSettingsAdmin:
    return SystemSettingsAdmin(
        settings=_read_settings(data),
        runtime_limits=_read_runtime_limits(data),
        task_timeouts=_read_task_timeouts(data),
        observability=_read_observability(data),
        server_log_retention=_read_server_log_retention(data),
    )


def _read_settings(data: dict[str, Any]) -> Settings:
    server = _mapping(data.get("server"), "config.yaml server section missing")
    settings = _mapping(server.get("settings"), "config.yaml server.settings section missing")
    missing = [key for key in ("intent_timeout", "reason_timeout") if key not in settings]
    if missing:
        raise HTTPException(500, f"config.yaml server.settings missing required fields: {', '.join(missing)}")
    return Settings(
        intent_timeout=int(settings["intent_timeout"]),
        reason_timeout=int(settings["reason_timeout"]),
    )


def _read_runtime_limits(data: dict[str, Any]) -> RuntimeLimits:
    dispatcher = _mapping(data.get("dispatcher"), "config.yaml dispatcher section missing")
    runtime = _mapping(dispatcher.get("runtime"), "config.yaml dispatcher.runtime section missing")
    missing = [
        key
        for key in (
            "max_workers",
            "max_running_projects",
            "max_project_workers",
            "interval",
            "healthcheck_timeout",
        )
        if key not in runtime
    ]
    if missing:
        raise HTTPException(500, f"config.yaml dispatcher.runtime missing: {', '.join(missing)}")
    return RuntimeLimits(
        max_workers=int(runtime["max_workers"]),
        max_running_projects=int(runtime["max_running_projects"]),
        max_project_workers=int(runtime["max_project_workers"]),
        interval=int(runtime["interval"]),
        healthcheck_timeout=int(runtime["healthcheck_timeout"]),
    )


def _read_task_timeouts(data: dict[str, Any]) -> TaskTimeouts:
    tasks = _mapping(data.get("tasks"), "config.yaml tasks section missing")
    try:
        return TaskTimeouts(
            bootstrap=BootstrapTaskTimeouts(
                timeout=int(tasks["bootstrap"]["timeout"]),
                conclude_timeout=int(tasks["bootstrap"]["conclude_timeout"]),
            ),
            explore=ExploreTaskTimeouts(
                timeout=int(tasks["explore"]["timeout"]),
                conclude_timeout=int(tasks["explore"]["conclude_timeout"]),
            ),
            reason=ReasonTaskTimeouts(
                timeout=int(tasks["reason"]["timeout"]),
                max_intents=int(tasks["reason"].get("max_intents", 3)),
            ),
        )
    except (KeyError, TypeError) as exc:
        raise HTTPException(500, f"config.yaml tasks missing or invalid: {exc}") from exc


def _read_observability(data: dict[str, Any]) -> ObservabilitySettings:
    observability = _mapping(data.get("observability"), "config.yaml observability section missing")
    record_set: set[str] = set(observability.get("record") or [])
    return ObservabilitySettings(
        enabled=bool(observability.get("enabled", True)),
        record_prompts="prompts" in record_set,
        record_stdout="stdout" in record_set,
        record_stderr="stderr" in record_set,
        record_raw_worker_stream=bool(observability.get("record_raw_worker_stream", False)),
        max_event_bytes=int(observability.get("max_event_bytes", 16384)),
        max_bytes_per_execution=int(observability.get("max_bytes_per_execution", 10485760)),
        flush_interval_ms=int(observability.get("flush_interval_ms", 250)),
        flush_max_bytes=int(observability.get("flush_max_bytes", 8192)),
        retention_days=int(observability.get("retention_days", 14)),
        redaction_patterns=observability.get("redaction_patterns") or [],
    )


def _read_server_log_retention(data: dict[str, Any]) -> ServerLogRetention:
    server = _mapping(data.get("server"), "config.yaml server section missing")
    log = _mapping(server.get("log"), "config.yaml server.log section missing")
    retention = _mapping(server.get("retention"), "config.yaml server.retention section missing")
    log_format = str(log.get("format", "text"))
    if log_format not in ("text", "json"):
        raise HTTPException(500, f"config.yaml server.log.format must be 'text' or 'json', got {log_format!r}")
    return ServerLogRetention(
        log_level=str(log.get("level", "INFO")),
        log_format=log_format,  # type: ignore[arg-type]  # narrowed above
        retention_enabled=bool(retention.get("enabled", True)),
        retention_interval_seconds=int(retention.get("interval_seconds", 21600)),
    )


def _write_settings(data: dict[str, Any], body: Settings) -> None:
    server = _mutable_mapping(data, "server", "config.yaml server must be a mapping")
    server["settings"] = {
        "intent_timeout": body.intent_timeout,
        "reason_timeout": body.reason_timeout,
    }


def _write_runtime_limits(data: dict[str, Any], body: RuntimeLimits) -> None:
    dispatcher = _mutable_mapping(data, "dispatcher", "config.yaml dispatcher must be a mapping")
    dispatcher["runtime"] = body.model_dump()


def _write_task_timeouts(data: dict[str, Any], body: TaskTimeouts) -> None:
    tasks = _mutable_mapping(data, "tasks", "config.yaml tasks must be a mapping")
    reason_orig = tasks.get("reason")
    max_intents = body.reason.max_intents
    if "max_intents" not in body.reason.model_fields_set:
        max_intents = 3
        if isinstance(reason_orig, dict) and "max_intents" in reason_orig:
            max_intents = int(reason_orig["max_intents"])
    tasks["bootstrap"] = {
        "timeout": body.bootstrap.timeout,
        "conclude_timeout": body.bootstrap.conclude_timeout,
    }
    tasks["explore"] = {
        "timeout": body.explore.timeout,
        "conclude_timeout": body.explore.conclude_timeout,
    }
    tasks["reason"] = {
        "timeout": body.reason.timeout,
        "max_intents": max_intents,
    }


def _write_observability(data: dict[str, Any], body: ObservabilitySettings) -> None:
    record: list[str] = []
    if body.record_prompts:
        record.append("prompts")
    if body.record_stdout:
        record.append("stdout")
    if body.record_stderr:
        record.append("stderr")
    data["observability"] = {
        "enabled": body.enabled,
        "record": record,
        "record_raw_worker_stream": body.record_raw_worker_stream,
        "max_event_bytes": body.max_event_bytes,
        "max_bytes_per_execution": body.max_bytes_per_execution,
        "flush_interval_ms": body.flush_interval_ms,
        "flush_max_bytes": body.flush_max_bytes,
        "retention_days": body.retention_days,
        "redaction_patterns": body.redaction_patterns,
    }


def _write_server_log_retention(data: dict[str, Any], body: ServerLogRetention) -> None:
    server = _mutable_mapping(data, "server", "config.yaml server must be a mapping")
    server["log"] = {
        "level": body.log_level,
        "format": body.log_format,
    }
    server["retention"] = {
        "enabled": body.retention_enabled,
        "interval_seconds": body.retention_interval_seconds,
    }


def _mapping(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HTTPException(500, message)
    return value


def _mutable_mapping(data: dict[str, Any], key: str, message: str) -> dict[str, Any]:
    value = data.setdefault(key, {})
    if not isinstance(value, dict):
        raise HTTPException(500, message)
    return value
