from __future__ import annotations

from typing import Any

from cairn.server.domain.ids import SCOPED_ID_PREFIXES, project_id_from_counter, scoped_id_from_counter
from cairn.server.repositories import sql


class IdRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def next_project_id(self) -> str:
        sql.execute(self.conn, "UPDATE counters SET value = value + 1 WHERE name = 'project'")
        row = sql.fetchone(self.conn, "SELECT value FROM counters WHERE name = 'project'")
        assert row is not None
        return project_id_from_counter(row["value"])

    def next_scoped_id(self, project_id: str, kind: str) -> str:
        prefix = SCOPED_ID_PREFIXES[kind]
        sql.execute(
            self.conn,
            """
            INSERT INTO scoped_counters (project_id, kind, value)
            VALUES (:project_id, :kind, 0)
            ON CONFLICT (project_id, kind) DO NOTHING
            """,
            {"project_id": project_id, "kind": kind},
        )
        sql.execute(
            self.conn,
            "UPDATE scoped_counters SET value = value + 1 WHERE project_id = :project_id AND kind = :kind",
            {"project_id": project_id, "kind": kind},
        )
        row = sql.fetchone(
            self.conn,
            "SELECT value FROM scoped_counters WHERE project_id = :project_id AND kind = :kind",
            {"project_id": project_id, "kind": kind},
        )
        assert row is not None
        return scoped_id_from_counter(prefix, row["value"])

    def next_fact_id(self, project_id: str) -> str:
        return self.next_scoped_id(project_id, "fact")

    def next_intent_id(self, project_id: str) -> str:
        return self.next_scoped_id(project_id, "intent")

    def next_hint_id(self, project_id: str) -> str:
        return self.next_scoped_id(project_id, "hint")
