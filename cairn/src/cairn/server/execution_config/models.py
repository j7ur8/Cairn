from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn.server.models_pkg import TaskCapabilities
from cairn.shared.contracts import ProjectAiProfileSnapshot, TaskTimeouts
from cairn.shared.task_types import builtin_task_type_names

TASK_TYPES = builtin_task_type_names()


@dataclass(slots=True)
class ProjectExecutionConfigSnapshot:
    role_id: str | None
    role: dict[str, Any] | None
    proxy_id: str | None
    task_timeouts: TaskTimeouts
    ai_by_task: dict[str, list[ProjectAiProfileSnapshot]]
    capabilities_by_task: dict[str, TaskCapabilities]
    revision: dict[str, str]
