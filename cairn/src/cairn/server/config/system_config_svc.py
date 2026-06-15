from __future__ import annotations

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, save_dispatch_data
from cairn.shared.contracts import ServerLogRetention


def get_server_log_retention() -> ServerLogRetention:
    data = load_dispatch_data()
    server = data.get("server")
    if not isinstance(server, dict):
        raise HTTPException(500, "config.yaml server section missing")
    log = server.get("log")
    if not isinstance(log, dict):
        raise HTTPException(500, "config.yaml server.log section missing")
    retention = server.get("retention")
    if not isinstance(retention, dict):
        raise HTTPException(500, "config.yaml server.retention section missing")
    log_format = str(log.get("format", "text"))
    if log_format not in ("text", "json"):
        raise HTTPException(500, f"config.yaml server.log.format must be 'text' or 'json', got {log_format!r}")
    return ServerLogRetention(
        log_level=str(log.get("level", "INFO")),
        log_format=log_format,  # type: ignore[arg-type]  # narrowed above
        retention_enabled=bool(retention.get("enabled", True)),
        retention_interval_seconds=int(retention.get("interval_seconds", 21600)),
    )


def update_server_log_retention(body: ServerLogRetention) -> ServerLogRetention:
    data = load_dispatch_data()
    server = data.setdefault("server", {})
    if not isinstance(server, dict):
        raise HTTPException(500, "config.yaml server must be a mapping")
    server["log"] = {
        "level": body.log_level,
        "format": body.log_format,
    }
    server["retention"] = {
        "enabled": body.retention_enabled,
        "interval_seconds": body.retention_interval_seconds,
    }
    save_dispatch_data(data)
    return body
