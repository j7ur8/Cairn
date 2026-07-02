from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from cairn.shared.contracts.observability import ObservabilitySettings
from cairn.shared.contracts.runtime_limits import RuntimeLimits
from cairn.shared.contracts.settings import Settings
from cairn.shared.contracts.timeouts import TaskTimeouts


class ServerLogRetention(BaseModel):
    """server.log + server.retention subset of the System admin contract."""

    model_config = {"extra": "forbid"}

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    retention_enabled: bool = True
    retention_interval_seconds: int = Field(default=21600, ge=60)


class SystemSettingsAdmin(BaseModel):
    """Aggregate System admin contract exposed via GET/PUT /system-settings."""

    model_config = {"extra": "forbid"}

    settings: Settings
    runtime_limits: RuntimeLimits
    task_timeouts: TaskTimeouts
    observability: ObservabilitySettings
    server_log_retention: ServerLogRetention
    saved: bool = False
    reload_applied: bool = False
    reload_error: str | None = None
