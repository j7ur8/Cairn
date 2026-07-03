from __future__ import annotations

import base64
import json
from typing import Any

from cairn.server.domain.errors import DomainError
from cairn.server.domain.projects import require_project
from cairn.server.mappers.intents import build_intents, intent_to_model
from cairn.server.mappers.projects import project_meta_from_row, project_reason_from_row
from cairn.server.repositories.intents import IntentRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.schemas import ProjectPollStateResponse
from cairn.shared.contracts import (
    Fact,
    Hint,
    ProjectDetail,
    ProjectGraphDelta,
    ProjectSummary,
    ProjectSummaryPage,
    ProjectWorkSummary,
    ProjectWorkSummaryPage,
    parse_llm_hidden_event_kinds,
)


def list_project_summaries(conn: Any) -> list[ProjectSummary]:
    rows = ProjectRepository(conn).list_with_counts()
    return [project_summary_from_row(row) for row in rows]


def list_project_summaries_page(conn: Any, *, limit: int, cursor: str | None) -> ProjectSummaryPage:
    projects = ProjectRepository(conn)
    rows = projects.list_with_counts_page(limit=limit + 1, cursor=_decode_cursor(cursor))
    page_rows = rows[:limit]
    next_cursor = _encode_cursor(page_rows[-1]) if len(rows) > limit and page_rows else None
    return ProjectSummaryPage(items=[project_summary_from_row(row) for row in page_rows], next_cursor=next_cursor)


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


def list_project_work_summaries_page(conn: Any, *, limit: int, cursor: str | None) -> ProjectWorkSummaryPage:
    projects = ProjectRepository(conn)
    rows = projects.list_work_summaries_page(limit=limit + 1, cursor=_decode_cursor(cursor))
    page_rows = rows[:limit]
    batch = IntentRepository(conn).list_open_intent_projections_batch([row["id"] for row in page_rows])
    next_cursor = _encode_cursor(page_rows[-1]) if len(rows) > limit and page_rows else None
    return ProjectWorkSummaryPage(
        items=[project_work_summary_from_row(projects, row, batch.get(row["id"], [])) for row in page_rows],
        next_cursor=next_cursor,
    )


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
    )


def get_project_graph_delta(
    conn: Any,
    project_id: str,
    *,
    after_graph_revision: int | None,
    after_timeline_revision: int | None,
) -> ProjectGraphDelta:
    projects = ProjectRepository(conn)
    row = require_project(projects.get(project_id))
    graph_revision = int(row["graph_revision"])
    timeline_revision = int(row["timeline_revision"])
    include_graph = after_graph_revision is None or after_graph_revision < graph_revision
    include_timeline = after_timeline_revision is None or after_timeline_revision < timeline_revision
    return ProjectGraphDelta(
        facts=[Fact(**dict(fact)) for fact in projects.get_facts(project_id)] if include_graph else [],
        intents=build_intents(IntentRepository(conn).list_intent_projections(project_id)) if include_graph else [],
        hints=[Hint(**dict(hint)) for hint in projects.get_hints(project_id)] if include_timeline else [],
        graph_revision=graph_revision,
        timeline_revision=timeline_revision,
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


def _encode_cursor(row: Any) -> str:
    payload = {"created_at": row["created_at"], "id": row["id"]}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise DomainError("invalid pagination cursor", status_code=400) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("created_at"), str) or not isinstance(payload.get("id"), str):
        raise DomainError("invalid pagination cursor", status_code=400)
    return payload["created_at"], payload["id"]


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

