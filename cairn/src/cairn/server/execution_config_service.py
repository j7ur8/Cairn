from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from cairn.server.ai_profile_service import ai_snapshots_from_selections
from cairn.server.capabilities_service import (
    catalog_map_from_items,
    expand_task_capabilities,
    probe_per_task,
    selected_capabilities_to_internal,
)
from cairn.server.models_pkg.ai_profiles import ProjectAiProfileSnapshot, TaskAiProfileSelections
from cairn.server.models_pkg.capabilities import (
    TaskCapabilities,
    TaskCapabilitiesMap,
    TaskCapabilitySelectionMap,
)
from cairn.server.repositories import sql
from cairn.server.config.ai_profiles import yaml_ai_profile_secret
from cairn.server.config.capabilities import list_yaml_capabilities
from cairn.server.config.files import config_revision
from cairn.server.config.proxies import get_yaml_proxy
from cairn.server.config.roles import get_yaml_role_snapshot
from cairn.server.config.settings import get_yaml_settings
from cairn.shared.task_types import builtin_task_type_names


TASK_TYPES = builtin_task_type_names()


def build_worker_execution_payloads(
    *,
    capabilities: TaskCapabilitySelectionMap | None,
    ai_profiles: TaskAiProfileSelections,
    role_id: str | None,
    proxy_id: str | None,
) -> dict[str, dict[str, Any]]:
    rev = config_revision()
    settings = get_yaml_settings()
    role = get_yaml_role_snapshot(role_id) if role_id else None
    role_default_skill_ids = [str(item).strip() for item in (role or {}).get("default_skill_ids", []) if str(item).strip()]
    catalog = list_yaml_capabilities()
    catalog_map = catalog_map_from_items(catalog)
    selected_per_task = selected_capabilities_to_internal(capabilities)
    expanded_per_task, _warnings = expand_task_capabilities(
        selected_per_task,
        catalog_map,
        role_default_skill_ids=role_default_skill_ids,
    )
    health = probe_per_task(None, expanded_per_task, catalog_map)
    ai_snapshots = ai_snapshots_from_selections(ai_profiles)
    ai_by_task = {
        task: [snap for snap in ai_snapshots if snap.task_type == task]
        for task in TASK_TYPES
    }
    proxy = get_yaml_proxy(proxy_id).model_dump() if proxy_id else None
    payloads: dict[str, dict[str, Any]] = {}
    for task in TASK_TYPES:
        ai_chain: list[dict[str, Any]] = []
        for snap in ai_by_task[task]:
            item = snap.model_dump()
            item["sk"] = yaml_ai_profile_secret(snap.profile_id)
            ai_chain.append(item)
        task_caps = expanded_per_task.get(task) or TaskCapabilities()
        payloads[task] = {
            "task_type": task,
            "ai_profiles": ai_chain,
            "capabilities": task_caps.model_dump(),
            "role": role,
            "proxy": proxy,
            "settings": settings.model_dump(),
            "catalog": [item.model_dump() for item in catalog],
            "health": {key: [entry.model_dump() for entry in entries] for key, entries in health.items()},
            "config_revision": rev,
        }
    return payloads


def persist_worker_execution_configs(
    conn: Any,
    project_id: str,
    *,
    proxy_id: str | None,
    capabilities: TaskCapabilitySelectionMap | None,
    ai_profiles: TaskAiProfileSelections,
    role_id: str | None,
    now: str,
) -> None:
    """Persist the complete project-time worker execution snapshot."""
    payloads = build_worker_execution_payloads(
        capabilities=capabilities,
        ai_profiles=ai_profiles,
        role_id=role_id,
        proxy_id=proxy_id,
    )
    sql.execute(
        conn,
        "DELETE FROM worker_execution_configs WHERE project_id = :project_id",
        {"project_id": project_id},
    )
    for task, payload in payloads.items():
        rev = payload.get("config_revision") or config_revision()
        sql.execute(
            conn,
            """
            INSERT INTO worker_execution_configs (
                project_id, task_type, config_json,
                dispatch_sha256, capabilities_sha256, created_at
            ) VALUES (
                :project_id, :task_type, :config_json,
                :dispatch_sha256, :capabilities_sha256, :created_at
            )
            """,
            {
                "project_id": project_id,
                "task_type": task,
                "config_json": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                "dispatch_sha256": rev["dispatch_sha256"],
                "capabilities_sha256": rev["capabilities_sha256"],
                "created_at": now,
            },
        )


def load_worker_execution_config(
    conn: Any,
    project_id: str,
    task_type: str,
) -> dict[str, Any]:
    row = sql.fetchone(
        conn,
        """
        SELECT config_json
        FROM worker_execution_configs
        WHERE project_id = :project_id AND task_type = :task_type
        """,
        {"project_id": project_id, "task_type": task_type},
    )
    if row is None:
        raise HTTPException(404, f"execution config not found for {project_id}/{task_type}")
    data = json.loads(row["config_json"])
    if not isinstance(data, dict):
        raise HTTPException(500, f"invalid execution config for {project_id}/{task_type}")
    return data


def load_worker_execution_configs(conn: Any, project_id: str) -> dict[str, dict[str, Any]]:
    rows = sql.fetchall(
        conn,
        """
        SELECT task_type, config_json
        FROM worker_execution_configs
        WHERE project_id = :project_id
        ORDER BY task_type
        """,
        {"project_id": project_id},
    )
    return {row["task_type"]: json.loads(row["config_json"]) for row in rows}


def execution_ai_snapshots(configs: dict[str, dict[str, Any]]) -> list[ProjectAiProfileSnapshot]:
    snapshots: list[ProjectAiProfileSnapshot] = []
    for task_type in TASK_TYPES:
        config = configs.get(task_type) or {}
        for item in config.get("ai_profiles") or []:
            if isinstance(item, dict):
                snapshots.append(ProjectAiProfileSnapshot.model_validate(item))
    return snapshots


def execution_capabilities(configs: dict[str, dict[str, Any]]) -> TaskCapabilitiesMap:
    out: TaskCapabilitiesMap = {}
    for task_type in TASK_TYPES:
        config = configs.get(task_type) or {}
        raw = config.get("capabilities") or {}
        out[task_type] = TaskCapabilities.model_validate(raw)
    return out
