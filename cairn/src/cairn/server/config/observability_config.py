from __future__ import annotations

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, save_dispatch_data
from cairn.shared.contracts import ObservabilitySettings


def get_observability() -> ObservabilitySettings:
    data = load_dispatch_data()
    obs = data.get("observability")
    if not isinstance(obs, dict):
        raise HTTPException(500, "config.yaml observability section missing")
    record_set: set[str] = set(obs.get("record") or [])
    return ObservabilitySettings(
        enabled=bool(obs.get("enabled", True)),
        record_prompts="prompts" in record_set,
        record_stdout="stdout" in record_set,
        record_stderr="stderr" in record_set,
        record_raw_worker_stream=bool(obs.get("record_raw_worker_stream", False)),
        max_event_bytes=int(obs.get("max_event_bytes", 16384)),
        max_bytes_per_execution=int(obs.get("max_bytes_per_execution", 10485760)),
        flush_interval_ms=int(obs.get("flush_interval_ms", 250)),
        flush_max_bytes=int(obs.get("flush_max_bytes", 8192)),
        retention_days=int(obs.get("retention_days", 14)),
        redaction_patterns=obs.get("redaction_patterns") or [],
    )


def update_observability(body: ObservabilitySettings) -> ObservabilitySettings:
    record: list[str] = []
    if body.record_prompts:
        record.append("prompts")
    if body.record_stdout:
        record.append("stdout")
    if body.record_stderr:
        record.append("stderr")
    data = load_dispatch_data()
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
    save_dispatch_data(data)
    return body
