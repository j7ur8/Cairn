from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn.server.schemas import TaskCapabilities
from cairn.shared.contracts import ProjectAiProfileSnapshot, TaskTimeouts
from cairn.shared.task_types import builtin_task_type_names

TASK_TYPES = builtin_task_type_names()


@dataclass(slots=True)
class ProjectExecutionConfigSnapshot:
    role_id: str | None
    role: dict[str, Any] | None
    proxy_id: str | None
    container: dict[str, Any]
    workers: list[dict[str, Any]]
    proxies: list[dict[str, Any]]
    settings: dict[str, Any]
    catalog: list[dict[str, Any]]
    task_timeouts: TaskTimeouts
    ai_by_task: dict[str, list[ProjectAiProfileSnapshot]]
    capabilities_by_task: dict[str, TaskCapabilities]
    revision: dict[str, str]
    prompt_snapshot: dict[str, Any]
