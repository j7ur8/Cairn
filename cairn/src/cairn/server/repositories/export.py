from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn.server.domain.projects import require_project
from cairn.server.repositories import sql
from cairn.server.repositories.projects import ProjectRepository


@dataclass(frozen=True)
class ProjectExportData:
    project: Any
    facts: list[Any]
    hints: list[Any]
    intents: list[Any]
    sources_by_intent: dict[str, list[str]]


class ProjectExportQuery:
    def __init__(self, conn: Any):
        self.conn = conn

    def load_project_data(self, project_id: str) -> ProjectExportData:
        project = ProjectRepository(self.conn).get(project_id)
        require_project(project)
        facts = sql.fetchall(
            self.conn,
            "SELECT id, description FROM facts WHERE project_id = :project_id",
            {"project_id": project_id},
        )
        hints = sql.fetchall(
            self.conn,
            """
            SELECT content, creator, created_at
            FROM hints
            WHERE project_id = :project_id
            ORDER BY created_at
            """,
            {"project_id": project_id},
        )
        intents = sql.fetchall(
            self.conn,
            "SELECT * FROM intents WHERE project_id = :project_id ORDER BY created_at",
            {"project_id": project_id},
        )
        sources_by_intent = {
            row["intent_id"]: row["fact_ids"] or []
            for row in sql.fetchall(
                self.conn,
                """
                SELECT intent_id, ARRAY_AGG(fact_id ORDER BY position, fact_id) AS fact_ids
                FROM intent_sources
                WHERE project_id = :project_id
                GROUP BY intent_id
                """,
                {"project_id": project_id},
            )
        }
        return ProjectExportData(
            project=project,
            facts=facts,
            hints=hints,
            intents=intents,
            sources_by_intent=sources_by_intent,
        )
