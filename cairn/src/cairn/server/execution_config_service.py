from __future__ import annotations

import json
from typing import Any

from cairn.server.ai_profile_service import load_project_ai_snapshots
from cairn.server.capabilities_service import load_project_capabilities_per_task
from cairn.server.yaml_config import (
    config_revision,
    get_yaml_proxy,
    get_yaml_settings,
    yaml_ai_profile_secret,
)


TASK_TYPES = ("bootstrap", "explore", "reason")


def persist_worker_execution_configs(
    conn: Any,
    project_id: str,
    *,
    proxy_id: str | None,
    now: str,
) -> None:
    """Persist the project-time execution snapshot.

    The dispatcher still consumes the legacy project_ai_profiles /
    project_capability_snapshots tables during this compatibility
    stage. This table is the single consolidated record for audits and
    the future dispatch path.
    """
    rev = config_revision()
    settings = get_yaml_settings()
    ai_by_task = {
        task: [snap for snap in load_project_ai_snapshots(conn, project_id) if snap.task_type == task]
        for task in TASK_TYPES
    }
    caps_by_task = load_project_capabilities_per_task(conn, project_id)
    proxy = get_yaml_proxy(proxy_id).model_dump() if proxy_id else None
    conn.execute("DELETE FROM worker_execution_configs WHERE project_id = ?", (project_id,))
    for task in TASK_TYPES:
        ai_chain = []
        for snap in ai_by_task[task]:
            item = snap.model_dump()
            item["sk"] = yaml_ai_profile_secret(snap.profile_id)
            ai_chain.append(item)
        payload = {
            "task_type": task,
            "ai_profiles": ai_chain,
            "capabilities": (caps_by_task.get(task).model_dump() if caps_by_task.get(task) else None),
            "proxy": proxy,
            "settings": settings.model_dump(),
        }
        conn.execute(
            """
            INSERT INTO worker_execution_configs (
                project_id, task_type, config_json,
                dispatch_sha256, capabilities_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                task,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                rev["dispatch_sha256"],
                rev["capabilities_sha256"],
                now,
            ),
        )

