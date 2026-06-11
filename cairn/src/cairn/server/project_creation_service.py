from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException

from cairn.server.models_pkg.ai_profiles import TaskAiProfileSelections
from cairn.server.models_pkg.capabilities import (
    TaskCapabilitiesMap,
    TaskCapabilitySelectionMap,
)
from cairn.server.models_pkg.projects import (
    CreateHintInline,
    Fact,
    Hint,
    ProjectDetail,
    ProjectMeta,
    hidden_kinds_from_visible,
)
from cairn.server.models_pkg.proxies import ProxySummary
from cairn.shared.protocol_models import TaskTimeouts
from cairn.server.ai_profile_service import (
    require_complete_ai_profile_selections,
)
from cairn.server.repositories import sql
from cairn.server.services import next_hint_id, next_project_id, utcnow
from cairn.server.execution_config_service import persist_worker_execution_configs
from cairn.server.config.proxies import get_yaml_proxy


@dataclass(slots=True)
class ProjectCreationDraft:
    title: str
    origin: str
    goal: str
    hints: list[CreateHintInline] | None = None
    capabilities: TaskCapabilitySelectionMap | None = None
    capability_snapshots: TaskCapabilitiesMap | None = None
    ai_profiles: TaskAiProfileSelections | None = None
    task_timeouts: TaskTimeouts | None = None
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
        sql.execute(
            conn,
            """
            INSERT INTO projects (
                id, title, status, created_at, proxy_id, llm_hidden_event_kinds
            ) VALUES (
                :id, :title, :status, :created_at, :proxy_id, :llm_hidden_event_kinds
            )
            """,
            {
                "id": pid,
                "title": draft.title,
                "status": draft.status,
                "created_at": now,
                "proxy_id": draft.proxy_id,
                "llm_hidden_event_kinds": json.dumps(hidden_event_kinds, ensure_ascii=False),
            },
        )
    except Exception as exc:
        raise HTTPException(400, f"invalid project create request: {exc}") from exc

    sql.execute(
        conn,
        """
        INSERT INTO facts (id, project_id, description)
        VALUES (:id, :project_id, :description)
        """,
        {"id": "origin", "project_id": pid, "description": draft.origin},
    )
    sql.execute(
        conn,
        """
        INSERT INTO facts (id, project_id, description)
        VALUES (:id, :project_id, :description)
        """,
        {"id": "goal", "project_id": pid, "description": draft.goal},
    )

    hints: list[Hint] = []
    for hint in draft.hints or []:
        hid = next_hint_id(conn, pid)
        sql.execute(
            conn,
            """
            INSERT INTO hints (id, project_id, content, creator, created_at)
            VALUES (:id, :project_id, :content, :creator, :created_at)
            """,
            {
                "id": hid,
                "project_id": pid,
                "content": hint.content,
                "creator": hint.creator,
                "created_at": now,
            },
        )
        hints.append(Hint(id=hid, content=hint.content, creator=hint.creator, created_at=now))

    ai_profiles = require_complete_ai_profile_selections(draft.ai_profiles)
    if draft.task_timeouts is None:
        raise HTTPException(422, "task_timeouts is required")
    persist_worker_execution_configs(
        conn,
        pid,
        proxy_id=draft.proxy_id,
        capabilities=draft.capabilities,
        ai_profiles=ai_profiles,
        role_id=draft.role_id,
        task_timeouts=draft.task_timeouts,
        now=now,
    )

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
