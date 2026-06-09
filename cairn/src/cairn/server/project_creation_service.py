from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException

from cairn.server.capabilities_service import (
    expand_task_capabilities,
    get_catalog_map,
    persist_project_capabilities_per_task,
    persist_probe_result,
    probe_per_task,
    selected_capabilities_to_internal,
    sync_catalog_from_yaml,
)
from cairn.server.models import Fact, Hint, ProjectDetail, ProjectMeta, ProxySummary
from cairn.server.models_pkg.ai_profiles import TaskAiProfileSelections
from cairn.server.models_pkg.capabilities import (
    TaskCapabilitiesMap,
    TaskCapabilitySelectionMap,
)
from cairn.server.models_pkg.projects import CreateHintInline, hidden_kinds_from_visible
from cairn.server.ai_profile_service import (
    persist_project_ai_selections,
    require_complete_ai_profile_selections,
)
from cairn.server.services import next_hint_id, next_project_id, utcnow
from cairn.server.execution_config_service import persist_worker_execution_configs
from cairn.server.yaml_config import get_yaml_proxy, get_yaml_role_snapshot


@dataclass(slots=True)
class ProjectCreationDraft:
    title: str
    origin: str
    goal: str
    hints: list[CreateHintInline] | None = None
    capabilities: TaskCapabilitySelectionMap | None = None
    capability_snapshots: TaskCapabilitiesMap | None = None
    ai_profiles: TaskAiProfileSelections | None = None
    role_id: str | None = None
    proxy_id: str | None = None
    llm_visible_event_kinds: list[str] | None = None
    llm_hidden_event_kinds: list[str] | None = None
    status: Literal["active", "stopped"] = "active"
    project_id: str | None = None


def create_project_from_draft(
    conn: Any,
    draft: ProjectCreationDraft,
) -> ProjectDetail:
    pid = draft.project_id or next_project_id(conn)
    now = utcnow()
    hidden_event_kinds = (
        list(draft.llm_hidden_event_kinds)
        if draft.llm_hidden_event_kinds is not None
        else hidden_kinds_from_visible(draft.llm_visible_event_kinds)
    )

    proxy_summary: ProxySummary | None = None
    if draft.proxy_id:
        try:
            proxy = get_yaml_proxy(draft.proxy_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(400, f"proxy_id not found: {draft.proxy_id}") from exc
            raise
        proxy_summary = ProxySummary(
            id=proxy.id,
            name=proxy.name,
            type=proxy.type,
            host=proxy.host,
            port=proxy.port,
            has_auth=proxy.has_auth,
            created_at=proxy.created_at,
            updated_at=proxy.updated_at,
        )

    try:
        conn.execute(
            """
            INSERT INTO projects (
                id, title, status, created_at, proxy_id, llm_hidden_event_kinds
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                draft.title,
                draft.status,
                now,
                draft.proxy_id,
                json.dumps(hidden_event_kinds, ensure_ascii=False),
            ),
        )
    except Exception as exc:
        raise HTTPException(400, f"invalid project create request: {exc}") from exc

    conn.execute(
        "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
        ("origin", pid, draft.origin),
    )
    conn.execute(
        "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
        ("goal", pid, draft.goal),
    )

    hints: list[Hint] = []
    for hint in draft.hints or []:
        hid = next_hint_id(conn, pid)
        conn.execute(
            "INSERT INTO hints (id, project_id, content, creator, created_at) VALUES (?, ?, ?, ?, ?)",
            (hid, pid, hint.content, hint.creator, now),
        )
        hints.append(Hint(id=hid, content=hint.content, creator=hint.creator, created_at=now))

    role = _load_role(conn, draft.role_id)
    role_default_skill_ids = _role_default_skill_ids(role)
    selected_per_task = (
        draft.capability_snapshots
        if draft.capability_snapshots is not None
        else selected_capabilities_to_internal(draft.capabilities)
    )
    sync_catalog_from_yaml(conn)
    catalog_map = get_catalog_map(conn)
    expanded_per_task, _expand_warnings = expand_task_capabilities(
        selected_per_task,
        catalog_map,
        role_default_skill_ids=role_default_skill_ids,
    )
    persist_project_capabilities_per_task(conn, pid, expanded_per_task, now)
    health_per_task = probe_per_task(conn, expanded_per_task, catalog_map)
    persist_probe_result(conn, health_per_task)

    if role is not None:
        _insert_role_snapshot(conn, pid, role, now)

    persist_project_ai_selections(
        conn,
        pid,
        require_complete_ai_profile_selections(draft.ai_profiles),
        now,
    )
    persist_worker_execution_configs(conn, pid, proxy_id=draft.proxy_id, now=now)

    return ProjectDetail(
        project=ProjectMeta(
            id=pid,
            title=draft.title,
            status=draft.status,
            created_at=now,
            reason=None,
            llm_hidden_event_kinds=hidden_event_kinds,
        ),
        facts=[
            Fact(id="origin", description=draft.origin),
            Fact(id="goal", description=draft.goal),
        ],
        intents=[],
        hints=hints,
        proxy=proxy_summary,
    )


def proxy_summary_from_row(row: Any) -> ProxySummary:
    return ProxySummary(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        host=row["host"],
        port=row["port"],
        has_auth=bool(row["username"] or row["password"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _load_role(conn: Any, role_id: str | None) -> Any | None:
    if not role_id:
        return None
    role = get_yaml_role_snapshot(role_id)
    if role is None:
        raise HTTPException(404, f"Role {role_id} not found or unavailable")
    return role


def _role_default_skill_ids(role: Any | None) -> list[str]:
    if role is None:
        return []
    return [str(item).strip() for item in role["default_skill_ids"] if str(item).strip()]


def _insert_role_snapshot(
    conn: Any,
    project_id: str,
    role: Any,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO project_roles (
            project_id, role_id, role_name, role_prompt, role_prompt_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, role["id"], role["name"], role["prompt"], role["prompt_sha256"], now),
    )
