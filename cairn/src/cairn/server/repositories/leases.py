from __future__ import annotations

from typing import Any

from cairn.server.domain.lease_cleanup import lease_cutoff
from cairn.server.repositories import sql


class LeaseRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def intent_timeout(self) -> int:
        row = sql.fetchone(self.conn, "SELECT intent_timeout FROM settings WHERE id = 1")
        assert row is not None
        return row["intent_timeout"]

    def reason_timeout(self) -> int:
        row = sql.fetchone(self.conn, "SELECT reason_timeout FROM settings WHERE id = 1")
        assert row is not None
        return row["reason_timeout"]

    def expire_workers(self, project_id: str | None = None) -> None:
        query = """
            UPDATE intents
            SET worker = NULL
            WHERE to_fact_id IS NULL
              AND worker IS NOT NULL
              AND last_heartbeat_at IS NOT NULL
              AND last_heartbeat_at < :cutoff
        """
        params: dict[str, str] = {"cutoff": lease_cutoff(self.intent_timeout())}
        project_rows = sql.fetchall(
            self.conn,
            """
            SELECT DISTINCT project_id
            FROM intents
            WHERE to_fact_id IS NULL
              AND worker IS NOT NULL
              AND last_heartbeat_at IS NOT NULL
              AND last_heartbeat_at < :cutoff
              AND (:project_id IS NULL OR project_id = :project_id)
            """,
            {"cutoff": params["cutoff"], "project_id": project_id},
        )
        if project_id is not None:
            query = query.replace("WHERE ", "WHERE project_id = :project_id AND ", 1)
            params["project_id"] = project_id
        sql.execute(self.conn, query, params)
        for row in project_rows:
            sql.execute(
                self.conn,
                "UPDATE projects SET graph_revision = graph_revision + 1 WHERE id = :project_id",
                {"project_id": row["project_id"]},
            )

    def expire_reason_leases(self, project_id: str | None = None) -> None:
        query = """
            UPDATE projects
            SET reason_worker = NULL,
                reason_run_id = NULL,
                reason_trigger = NULL,
                reason_started_at = NULL,
                reason_last_heartbeat_at = NULL
            WHERE reason_worker IS NOT NULL
              AND reason_last_heartbeat_at IS NOT NULL
              AND reason_last_heartbeat_at < :cutoff
        """
        params: dict[str, str] = {"cutoff": lease_cutoff(self.reason_timeout())}
        project_rows = sql.fetchall(
            self.conn,
            """
            SELECT id
            FROM projects
            WHERE reason_worker IS NOT NULL
              AND reason_last_heartbeat_at IS NOT NULL
              AND reason_last_heartbeat_at < :cutoff
              AND (:project_id IS NULL OR id = :project_id)
            """,
            {"cutoff": params["cutoff"], "project_id": project_id},
        )
        if project_id is not None:
            query = query.replace("WHERE ", "WHERE id = :project_id AND ", 1)
            params["project_id"] = project_id
        sql.execute(self.conn, query, params)
        for row in project_rows:
            sql.execute(
                self.conn,
                "UPDATE projects SET graph_revision = graph_revision + 1 WHERE id = :project_id",
                {"project_id": row["id"]},
            )
