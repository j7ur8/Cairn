from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql


class IntentRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def insert_open(
        self,
        *,
        project_id: str,
        intent_id: str,
        source_fact_ids: list[str],
        description: str,
        creator: str,
        worker: str | None,
        now: str,
    ) -> None:
        claimed = worker is not None
        sql.execute(
            self.conn,
            """
            INSERT INTO intents (
                id, project_id, to_fact_id, description, creator, worker,
                last_heartbeat_at, created_at, concluded_at
            ) VALUES (
                :intent_id, :project_id, NULL, :description, :creator, :worker,
                :last_heartbeat_at, :created_at, NULL
            )
            """,
            {
                "intent_id": intent_id,
                "project_id": project_id,
                "description": description,
                "creator": creator,
                "worker": worker,
                "last_heartbeat_at": now if claimed else None,
                "created_at": now,
            },
        )
        self.insert_sources(intent_id, project_id, source_fact_ids)

    def insert_completed_goal(
        self,
        *,
        project_id: str,
        intent_id: str,
        source_fact_ids: list[str],
        description: str,
        worker: str,
        now: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO intents (
                id, project_id, to_fact_id, description, creator, worker,
                last_heartbeat_at, created_at, concluded_at
            ) VALUES (
                :intent_id, :project_id, 'goal', :description, :worker, :worker,
                :now, :now, :now
            )
            """,
            {
                "intent_id": intent_id,
                "project_id": project_id,
                "description": description,
                "worker": worker,
                "now": now,
            },
        )
        self.insert_sources(intent_id, project_id, source_fact_ids)

    def insert_concluded(
        self,
        *,
        project_id: str,
        intent_id: str,
        to_fact_id: str,
        source_fact_ids: list[str],
        description: str,
        creator: str,
        now: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO intents (
                id, project_id, to_fact_id, description, creator, worker,
                last_heartbeat_at, created_at, concluded_at
            ) VALUES (
                :intent_id, :project_id, :to_fact_id, :description, :creator, :creator,
                :now, :now, :now
            )
            """,
            {
                "intent_id": intent_id,
                "project_id": project_id,
                "to_fact_id": to_fact_id,
                "description": description,
                "creator": creator,
                "now": now,
            },
        )
        self.insert_sources(intent_id, project_id, source_fact_ids)

    def insert_sources(self, intent_id: str, project_id: str, fact_ids: list[str]) -> None:
        for position, fact_id in enumerate(fact_ids):
            sql.execute(
                self.conn,
                """
                INSERT INTO intent_sources (intent_id, project_id, fact_id, position)
                VALUES (:intent_id, :project_id, :fact_id, :position)
                """,
                {
                    "intent_id": intent_id,
                    "project_id": project_id,
                    "fact_id": fact_id,
                    "position": position,
                },
            )

    def insert_fact(self, project_id: str, fact_id: str, description: str) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO facts (id, project_id, description)
            VALUES (:fact_id, :project_id, :description)
            """,
            {"fact_id": fact_id, "project_id": project_id, "description": description},
        )

    def delete_intent(self, project_id: str, intent_id: str) -> None:
        sql.execute(
            self.conn,
            "DELETE FROM intents WHERE id = :intent_id AND project_id = :project_id",
            {"intent_id": intent_id, "project_id": project_id},
        )

    def get_intent(self, project_id: str, intent_id: str) -> Any:
        return sql.fetchone(
            self.conn,
            "SELECT * FROM intents WHERE id = :intent_id AND project_id = :project_id",
            {"intent_id": intent_id, "project_id": project_id},
        )

    def source_fact_ids(self, project_id: str, intent_id: str) -> list[str]:
        rows = sql.fetchall(
            self.conn,
            """
            SELECT fact_id
            FROM intent_sources
            WHERE intent_id = :intent_id AND project_id = :project_id
            ORDER BY position, fact_id
            """,
            {"intent_id": intent_id, "project_id": project_id},
        )
        return [row["fact_id"] for row in rows]
