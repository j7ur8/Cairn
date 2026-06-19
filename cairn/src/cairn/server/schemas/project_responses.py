from __future__ import annotations

from pydantic import BaseModel

from cairn.shared.contracts import Fact, Intent, ProjectMeta, ProjectReason


class ReopenResponse(BaseModel):
    project: ProjectMeta
    fact: Fact
    intent: Intent


class ProjectPollStateResponse(BaseModel):
    project_id: str
    title: str
    status: str
    reason: ProjectReason | None = None
    fact_count: int
    intent_count: int
    hint_count: int
    graph_revision: int
    timeline_revision: int
