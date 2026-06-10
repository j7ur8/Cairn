from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn.shared.dispatch_config import DispatchConfig, WorkerConfig
from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.shared.capability_projection import (
    capability_manifest_payload,
    project_capability_data,
)
from cairn.shared.protocol_models import Intent, ProjectDetail


@dataclass(slots=True)
class WorkerTaskContext:
    config: DispatchConfig
    client: CairnClient
    container_manager: ContainerManager
    project: ProjectDetail
    worker: WorkerConfig
    task_type: str
    intent: Intent | None = None


def project_execution_config(
    client: CairnClient,
    project_id: str,
    task_type: str,
    reporter: ExecutionReporter,
    phase: str,
) -> dict | None:
    response = client.get_project_execution_config(project_id, task_type)
    if response.ok and isinstance(response.data, dict):
        return response.data
    reporter.emit_error(phase, "error", f"execution config fetch failed status={response.status_code}")
    return None


def project_role_data(execution_config: dict | None) -> dict | None:
    if not execution_config:
        return None
    role = execution_config.get("role")
    if not isinstance(role, dict):
        return {"role": None}
    return {
        "role": {
            "project_id": "",
            "role_id": role.get("id") or "",
            "role_name": role.get("name") or "",
            "role_prompt": role.get("prompt") or "",
            "role_prompt_sha256": role.get("prompt_sha256") or "",
            "created_at": "",
        }
    }
