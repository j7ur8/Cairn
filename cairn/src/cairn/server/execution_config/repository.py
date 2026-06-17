from __future__ import annotations

import json
from typing import Any

from cairn.server.domain.errors import ServerInvariantError
from cairn.server.execution_config.models import TASK_TYPES, ProjectExecutionConfigSnapshot
from cairn.server.models_pkg import TaskCapabilities
from cairn.server.repositories import sql


def insert_project_execution_config(
    conn: Any,
    project_id: str,
    snapshot: ProjectExecutionConfigSnapshot,
    *,
    now: str,
) -> None:
    existing = sql.fetchone(
        conn,
        "SELECT version FROM project_execution_configs WHERE project_id = :project_id",
        {"project_id": project_id},
    )
    if existing is not None:
        raise ServerInvariantError("project execution config already exists")
    sql.execute(
        conn,
        """
        INSERT INTO project_execution_configs (
            project_id, version, role_id, role_json, proxy_id,
            dispatch_sha256, resources_sha256, prompt_group, prompts_json,
            prompts_sha256, created_at, updated_at
        ) VALUES (
            :project_id, :version, :role_id, :role_json, :proxy_id,
            :dispatch_sha256, :resources_sha256, :prompt_group, :prompts_json,
            :prompts_sha256, :created_at, :updated_at
        )
        """,
        {
            "project_id": project_id,
            "version": 1,
            "role_id": snapshot.role_id,
            "role_json": json.dumps(snapshot.role, ensure_ascii=False, sort_keys=True) if snapshot.role is not None else None,
            "proxy_id": snapshot.proxy_id,
            "dispatch_sha256": snapshot.revision["dispatch_sha256"],
            "resources_sha256": snapshot.revision["resources_sha256"],
            "prompt_group": snapshot.prompt_snapshot["prompt_group"],
            "prompts_json": json.dumps(snapshot.prompt_snapshot, ensure_ascii=False, sort_keys=True),
            "prompts_sha256": snapshot.prompt_snapshot["prompts_sha256"],
            "created_at": now,
            "updated_at": now,
        },
    )
    for task in TASK_TYPES:
        timeout = getattr(snapshot.task_timeouts, task)
        conclude_timeout = getattr(timeout, "conclude_timeout", None)
        sql.execute(
            conn,
            """
            INSERT INTO project_execution_task_timeouts (
                project_id, task_type, timeout, conclude_timeout
            ) VALUES (:project_id, :task_type, :timeout, :conclude_timeout)
            """,
            {
                "project_id": project_id,
                "task_type": task,
                "timeout": timeout.timeout,
                "conclude_timeout": conclude_timeout,
            },
        )
        sql.execute(
            conn,
            """
            INSERT INTO project_execution_capabilities (
                project_id, task_type, capabilities_json
            ) VALUES (:project_id, :task_type, :capabilities_json)
            """,
            {
                "project_id": project_id,
                "task_type": task,
                "capabilities_json": json.dumps(
                    (snapshot.capabilities_by_task.get(task) or TaskCapabilities()).model_dump(),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )
        for snap in snapshot.ai_by_task.get(task) or []:
            sql.execute(
                conn,
                """
                INSERT INTO project_execution_ai_profiles (
                    project_id, task_type, role, position, profile_id,
                    snapshot_name, snapshot_worker_type, snapshot_provider,
                    snapshot_base_url, snapshot_model, snapshot_reasoning_type,
                    snapshot_api_key_env
                ) VALUES (
                    :project_id, :task_type, :role, :position, :profile_id,
                    :snapshot_name, :snapshot_worker_type, :snapshot_provider,
                    :snapshot_base_url, :snapshot_model, :snapshot_reasoning_type,
                    :snapshot_api_key_env
                )
                """,
                {"project_id": project_id, **snap.model_dump()},
            )


def get_header(conn: Any, project_id: str) -> Any | None:
    return sql.fetchone(
        conn,
        "SELECT * FROM project_execution_configs WHERE project_id = :project_id",
        {"project_id": project_id},
    )


def get_timeout_rows(conn: Any, project_id: str) -> list[Any]:
    return sql.fetchall(
        conn,
        """
        SELECT * FROM project_execution_task_timeouts
        WHERE project_id = :project_id
        """,
        {"project_id": project_id},
    )


def get_ai_rows(conn: Any, project_id: str, task_type: str | None = None) -> list[Any]:
    params: dict[str, Any] = {"project_id": project_id}
    task_filter = ""
    if task_type is not None:
        task_filter = "AND task_type = :task_type"
        params["task_type"] = task_type
    return sql.fetchall(
        conn,
        f"""
        SELECT *
        FROM project_execution_ai_profiles
        WHERE project_id = :project_id
          {task_filter}
        ORDER BY task_type, CASE role WHEN 'primary' THEN 0 ELSE 1 END, position
        """,
        params,
    )


def get_capability_rows(conn: Any, project_id: str, task_type: str | None = None) -> list[Any]:
    params: dict[str, Any] = {"project_id": project_id}
    task_filter = ""
    if task_type is not None:
        task_filter = "AND task_type = :task_type"
        params["task_type"] = task_type
    return sql.fetchall(
        conn,
        f"""
        SELECT task_type, capabilities_json
        FROM project_execution_capabilities
        WHERE project_id = :project_id
          {task_filter}
        """,
        params,
    )
