from __future__ import annotations

from typing import Any

from cairn.server.config.proxies import get_yaml_proxy
from cairn.server.domain.errors import DomainError
from cairn.server.domain.projects import require_project
from cairn.server.mappers.intents import build_intents, intent_to_model
from cairn.server.mappers.projects import project_meta_from_row, project_reason_from_row
from cairn.server.models_pkg import ProjectPollStateResponse
from cairn.server.repositories.intents import IntentRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.shared.contracts import (
    Fact,
    Hint,
    ProjectDetail,
    ProjectSummary,
    ProjectWorkSummary,
    ProxySummary,
    parse_llm_hidden_event_kinds,
)


def list_project_summaries(conn: Any) -> list[ProjectSummary]:
    rows = ProjectRepository(conn).list_with_counts()
    return [project_summary_from_row(row) for row in rows]


def list_project_work_summaries(conn: Any) -> list[ProjectWorkSummary]:
    projects = ProjectRepository(conn)
    rows = projects.list_work_summaries()
    batch = IntentRepository(conn).list_open_intent_projections_batch(
        [row["id"] for row in rows]
    )
    return [
        project_work_summary_from_row(projects, row, batch.get(row["id"], []))
        for row in rows
    ]


def get_project_detail(conn: Any, project_id: str) -> ProjectDetail:
    projects = ProjectRepository(conn)
    row = require_project(projects.get(project_id))
    facts = projects.get_facts(project_id)
    hints = projects.get_hints(project_id)
    return ProjectDetail(
        project=project_meta_from_row(row),
        facts=[Fact(**dict(fact)) for fact in facts],
        intents=build_intents(IntentRepository(conn).list_intent_projections(project_id)),
        hints=[Hint(**dict(hint)) for hint in hints],
        proxy=project_proxy_summary(row),
    )


def get_project_poll_state(conn: Any, project_id: str) -> ProjectPollStateResponse:
    row = require_project(ProjectRepository(conn).get_poll_state(project_id))
    return ProjectPollStateResponse(
        project_id=row["id"],
        title=row["title"],
        status=row["status"],
        reason=project_reason_from_row(row),
        fact_count=row["fact_count"],
        intent_count=row["intent_count"],
        hint_count=row["hint_count"],
        graph_revision=row["graph_revision"],
        timeline_revision=row["timeline_revision"],
    )


def project_summary_from_row(row: Any) -> ProjectSummary:
    return ProjectSummary(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        reason=project_reason_from_row(row),
        fact_count=row["fact_count"],
        intent_count=row["intent_count"],
        working_intent_count=row["working_intent_count"],
        unclaimed_intent_count=row["unclaimed_intent_count"],
        hint_count=row["hint_count"],
    )


def project_work_summary_from_row(
    projects: ProjectRepository,
    row: Any,
    open_intents: list[dict[str, Any]],
) -> ProjectWorkSummary:
    project_id = row["id"]
    return ProjectWorkSummary(
        id=project_id,
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        reason=project_reason_from_row(row),
        fact_count=row["fact_count"],
        intent_count=row["intent_count"],
        working_intent_count=row["working_intent_count"],
        unclaimed_intent_count=row["unclaimed_intent_count"],
        hint_count=row["hint_count"],
        config_version=row["config_version"],
        open_intents=[intent_to_model(i) for i in open_intents],
        llm_hidden_event_kinds=parse_llm_hidden_event_kinds(
            row["llm_hidden_event_kinds"]
            if "llm_hidden_event_kinds" in row.keys()
            else None
        ),
    )


def project_proxy_summary(row: Any) -> ProxySummary | None:
    proxy_id = row["proxy_id"] if "proxy_id" in row.keys() else None
    if not proxy_id:
        return None
    try:
        proxy = get_yaml_proxy(proxy_id)
    except DomainError:
        return None
    return ProxySummary(
        id=proxy.id,
        name=proxy.name,
        type=proxy.type,
        host=proxy.host,
        port=proxy.port,
        has_auth=proxy.has_auth,
        created_at=proxy.created_at,
        updated_at=proxy.updated_at,
    )
