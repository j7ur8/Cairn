from __future__ import annotations

from typing import Any

from cairn.server.execution_config.assembler import (
    load_project_execution_config,
    load_project_execution_configs,
)
from cairn.server.execution_config.patcher import (
    execution_ai_snapshots,
    execution_capabilities,
    execution_task_timeouts,
)
from cairn.server.execution_config.repository import insert_project_execution_config
from cairn.server.execution_config.snapshot_builder import build_project_execution_config_snapshot
from cairn.server.schemas import TaskCapabilitySelectionMap
from cairn.server.schemas.ai_profiles import TaskAiProfileSelections
from cairn.shared.contracts import TaskTimeouts


def persist_project_execution_configs(
    conn: Any,
    project_id: str,
    *,
    proxy_id: str | None,
    capabilities: TaskCapabilitySelectionMap | None,
    ai_profiles: TaskAiProfileSelections,
    role_id: str | None,
    task_timeouts: TaskTimeouts,
    now: str,
) -> None:
    snapshot = build_project_execution_config_snapshot(
        capabilities=capabilities,
        ai_profiles=ai_profiles,
        role_id=role_id,
        proxy_id=proxy_id,
        task_timeouts=task_timeouts,
    )
    insert_project_execution_config(conn, project_id, snapshot, now=now)


__all__ = [
    "execution_ai_snapshots",
    "execution_capabilities",
    "execution_task_timeouts",
    "load_project_execution_config",
    "load_project_execution_configs",
    "persist_project_execution_configs",
]
