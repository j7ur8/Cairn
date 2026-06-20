from __future__ import annotations

from cairn.server.ai_profile_service import ai_snapshots_from_selections
from cairn.server.capability_expansion import (
    catalog_map_from_items,
    expand_task_capabilities,
    selected_capabilities_to_internal,
)
from cairn.server.config.capabilities import list_yaml_capabilities
from cairn.server.config.files import config_revision
from cairn.server.config.roles import get_yaml_role_snapshot
from cairn.server.execution_config.models import TASK_TYPES, ProjectExecutionConfigSnapshot
from cairn.server.execution_config.prompt_snapshot import load_prompt_snapshot
from cairn.server.runtime_config import dispatch_config_path
from cairn.server.schemas import TaskCapabilitySelectionMap
from cairn.server.schemas.ai_profiles import TaskAiProfileSelections
from cairn.shared.config import load_dispatch_config
from cairn.shared.contracts import TaskTimeouts


def build_project_execution_config_snapshot(
    *,
    capabilities: TaskCapabilitySelectionMap | None,
    ai_profiles: TaskAiProfileSelections,
    role_id: str | None,
    proxy_id: str | None,
    task_timeouts: TaskTimeouts,
) -> ProjectExecutionConfigSnapshot:
    revision = config_revision()
    dispatch_config = load_dispatch_config(dispatch_config_path())
    prompt_snapshot = load_prompt_snapshot()
    role = get_yaml_role_snapshot(role_id) if role_id else None
    role_default_skill_ids = [
        str(item).strip()
        for item in (role or {}).get("default_skill_ids", [])
        if str(item).strip()
    ]
    catalog = list_yaml_capabilities()
    catalog_map = catalog_map_from_items(catalog)
    selected_per_task = selected_capabilities_to_internal(capabilities)
    expanded_per_task, _warnings = expand_task_capabilities(
        selected_per_task,
        catalog_map,
        role_default_skill_ids=role_default_skill_ids,
    )
    ai_snapshots = ai_snapshots_from_selections(ai_profiles)
    ai_by_task = {
        task: [snap for snap in ai_snapshots if snap.task_type == task]
        for task in TASK_TYPES
    }
    return ProjectExecutionConfigSnapshot(
        role_id=role_id,
        role=role,
        proxy_id=proxy_id,
        task_timeouts=task_timeouts,
        ai_by_task=ai_by_task,
        capabilities_by_task=expanded_per_task,
        revision=revision,
        prompt_snapshot=prompt_snapshot,
    )
