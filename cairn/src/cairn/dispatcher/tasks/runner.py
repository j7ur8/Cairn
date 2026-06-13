from __future__ import annotations

from dataclasses import dataclass

from cairn.dispatcher.capabilities import CapabilityInjection, inject_project_capabilities
from cairn.dispatcher.observability.reporter import AnyReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.roles import RoleInjection, inject_project_role
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.shared.capability_projection import project_capability_data
from cairn.shared.config import DispatchConfig


@dataclass(slots=True)
class PreparedTaskExecution:
    execution_config: dict
    task_timeout: dict
    capabilities: CapabilityInjection
    role: RoleInjection


def prepare_task_execution(
    *,
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    container_name: str,
    project_id: str,
    task_type: str,
    capability_scope: str,
    reporter: AnyReporter,
    phase: str,
    preloaded_execution_config: dict | None = None,
) -> PreparedTaskExecution | None:
    execution_config = preloaded_execution_config
    if execution_config is None:
        execution_config = project_execution_config(client, project_id, task_type, reporter, phase)
    task_timeout = project_task_timeout(execution_config, phase, reporter)
    if execution_config is None or task_timeout is None:
        return None
    capabilities = inject_project_capabilities(
        config,
        container_manager,
        container_name,
        project_id,
        task_type,
        capability_scope,
        project_capability_data(execution_config),
    )
    if capabilities.summary:
        reporter.emit_result("capabilities", capabilities.summary)
    for error in capabilities.errors:
        reporter.emit_error("capabilities", "error", error)

    role = inject_project_role(
        project_id,
        task_type,
        project_role_data(execution_config),
    )
    if role.summary:
        reporter.emit_result("role", role.summary)
    for error in role.errors or []:
        reporter.emit_error("role", "error", error)
    return PreparedTaskExecution(
        execution_config=execution_config,
        task_timeout=task_timeout,
        capabilities=capabilities,
        role=role,
    )


def project_execution_config(
    client: CairnClient,
    project_id: str,
    task_type: str,
    reporter: AnyReporter,
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


def project_task_timeout(execution_config: dict | None, phase: str, reporter: AnyReporter) -> dict | None:
    if not execution_config:
        reporter.emit_error(phase, "error", "execution config missing task_timeout")
        return None
    task_timeout = execution_config.get("task_timeout")
    if not isinstance(task_timeout, dict):
        reporter.emit_error(phase, "error", "execution config missing task_timeout")
        return None
    return task_timeout
