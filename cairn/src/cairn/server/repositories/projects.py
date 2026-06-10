from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql


class ProjectRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def list_with_counts(self) -> list[Any]:
        return sql.fetchall(self.conn, """
            SELECT p.*,
                (SELECT COUNT(*) FROM facts WHERE project_id = p.id) AS fact_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id) AS intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NOT NULL) AS working_intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NULL) AS unclaimed_intent_count,
                (SELECT COUNT(*) FROM hints WHERE project_id = p.id) AS hint_count
            FROM projects p
            ORDER BY p.created_at
        """)

    def get_facts(self, project_id: str) -> list[Any]:
        return sql.fetchall(
            self.conn,
            "SELECT * FROM facts WHERE project_id = :project_id",
            {"project_id": project_id},
        )

    def get_hints(self, project_id: str) -> list[Any]:
        return sql.fetchall(
            self.conn,
            "SELECT * FROM hints WHERE project_id = :project_id ORDER BY created_at",
            {"project_id": project_id},
        )

    def delete(self, project_id: str) -> None:
        sql.execute(self.conn, "DELETE FROM projects WHERE id = :project_id", {"project_id": project_id})

    def update_title(self, project_id: str, title: str) -> Any:
        sql.execute(
            self.conn,
            "UPDATE projects SET title = :title WHERE id = :project_id",
            {"title": title, "project_id": project_id},
        )
        return self.get(project_id)

    def update_status(self, project_id: str, status: str) -> Any:
        sql.execute(
            self.conn,
            "UPDATE projects SET status = :status WHERE id = :project_id",
            {"status": status, "project_id": project_id},
        )
        return self.get(project_id)

    def release_open_intents(self, project_id: str) -> None:
        sql.execute(
            self.conn,
            "UPDATE intents SET worker = NULL WHERE project_id = :project_id AND concluded_at IS NULL",
            {"project_id": project_id},
        )

    def complete(self, project_id: str) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE projects
            SET status = 'completed',
                reason_worker = NULL,
                reason_run_id = NULL,
                reason_trigger = NULL,
                reason_started_at = NULL,
                reason_last_heartbeat_at = NULL
            WHERE id = :project_id
            """,
            {"project_id": project_id},
        )

    def reopen(self, project_id: str) -> Any:
        sql.execute(
            self.conn,
            "UPDATE projects SET status = 'active' WHERE id = :project_id",
            {"project_id": project_id},
        )
        return self.get(project_id)

    def get(self, project_id: str) -> Any:
        return sql.fetchone(
            self.conn,
            "SELECT * FROM projects WHERE id = :project_id",
            {"project_id": project_id},
        )
