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

    def list_work_summaries(self) -> list[Any]:
        return sql.fetchall(self.conn, """
            SELECT p.*,
                COALESCE(pec.version, 0) AS config_version,
                (SELECT COUNT(*) FROM facts WHERE project_id = p.id) AS fact_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id) AS intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NOT NULL) AS working_intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NULL) AS unclaimed_intent_count,
                (SELECT COUNT(*) FROM hints WHERE project_id = p.id) AS hint_count
            FROM projects p
            LEFT JOIN project_execution_configs pec ON pec.project_id = p.id
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

    def existing_fact_ids(self, project_id: str, fact_ids: list[str]) -> set[str]:
        if not fact_ids:
            return set()
        rows = sql.fetchall(
            self.conn,
            """
            SELECT id
            FROM facts
            WHERE project_id = :project_id
              AND id = ANY(:fact_ids)
            """,
            {"project_id": project_id, "fact_ids": fact_ids},
        )
        return {row["id"] for row in rows}

    def completion_intents(self, project_id: str) -> list[Any]:
        return sql.fetchall(
            self.conn,
            "SELECT * FROM intents WHERE project_id = :project_id AND to_fact_id = 'goal'",
            {"project_id": project_id},
        )

    def insert_project(
        self,
        *,
        project_id: str,
        title: str,
        status: str,
        created_at: str,
        proxy_id: str | None,
        llm_hidden_event_kinds: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO projects (
                id, title, status, created_at, proxy_id, llm_hidden_event_kinds
            ) VALUES (
                :id, :title, :status, :created_at, :proxy_id, :llm_hidden_event_kinds
            )
            """,
            {
                "id": project_id,
                "title": title,
                "status": status,
                "created_at": created_at,
                "proxy_id": proxy_id,
                "llm_hidden_event_kinds": llm_hidden_event_kinds,
            },
        )

    def insert_fact(self, project_id: str, fact_id: str, description: str) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO facts (id, project_id, description)
            VALUES (:id, :project_id, :description)
            """,
            {"id": fact_id, "project_id": project_id, "description": description},
        )

    def insert_hint(self, project_id: str, hint_id: str, content: str, creator: str, created_at: str) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO hints (id, project_id, content, creator, created_at)
            VALUES (:id, :project_id, :content, :creator, :created_at)
            """,
            {
                "id": hint_id,
                "project_id": project_id,
                "content": content,
                "creator": creator,
                "created_at": created_at,
            },
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

    def update_proxy_id(self, project_id: str, proxy_id: str | None) -> None:
        sql.execute(
            self.conn,
            "UPDATE projects SET proxy_id = :proxy_id WHERE id = :project_id",
            {"project_id": project_id, "proxy_id": proxy_id},
        )

    def clear_proxy(self, proxy_id: str) -> None:
        sql.execute(
            self.conn,
            "UPDATE projects SET proxy_id = NULL WHERE proxy_id = :proxy_id",
            {"proxy_id": proxy_id},
        )

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
