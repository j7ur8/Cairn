from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql


def _intent_projection(row: Any, sources_by_intent: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "from": list(sources_by_intent.get(row["id"], [])),
        "to_fact_id": row["to_fact_id"],
        "description": row["description"],
        "creator": row["creator"],
        "worker": row["worker"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "created_at": row["created_at"],
        "concluded_at": row["concluded_at"],
    }


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

    def claim_open(self, project_id: str, intent_id: str, worker: str, now: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET worker = :worker, last_heartbeat_at = :now
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND (worker IS NULL OR worker = :worker)
            """,
            {"worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
        )
        return cursor.rowcount

    def heartbeat_open(self, project_id: str, intent_id: str, worker: str, now: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET last_heartbeat_at = :now
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND worker = :worker
            """,
            {"worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
        )
        return cursor.rowcount

    def release_open(self, project_id: str, intent_id: str, worker: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET worker = NULL
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND worker = :worker
            """,
            {"intent_id": intent_id, "project_id": project_id, "worker": worker},
        )
        return cursor.rowcount

    def conclude_open(self, project_id: str, intent_id: str, worker: str, fact_id: str, now: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET to_fact_id = :fact_id, worker = :worker, last_heartbeat_at = :now, concluded_at = :now
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND worker = :worker
            """,
            {"fact_id": fact_id, "worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
        )
        return cursor.rowcount

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

    def get_intent_projection(self, project_id: str, intent_id: str) -> dict[str, Any] | None:
        row = self.get_intent(project_id, intent_id)
        if row is None:
            return None
        return _intent_projection(row, {intent_id: self.source_fact_ids(project_id, intent_id)})

    def list_intent_projections(self, project_id: str) -> list[dict[str, Any]]:
        rows = sql.fetchall(
            self.conn,
            "SELECT * FROM intents WHERE project_id = :project_id ORDER BY created_at",
            {"project_id": project_id},
        )
        if not rows:
            return []
        source_rows = sql.fetchall(
            self.conn,
            """
            SELECT intent_id, fact_id
            FROM intent_sources
            WHERE project_id = :project_id
            ORDER BY intent_id, position, fact_id
            """,
            {"project_id": project_id},
        )
        sources_by_intent: dict[str, list[str]] = {}
        for source in source_rows:
            sources_by_intent.setdefault(source["intent_id"], []).append(source["fact_id"])
        return [_intent_projection(row, sources_by_intent) for row in rows]

    def list_open_intent_projections(self, project_id: str) -> list[dict[str, Any]]:
        rows = sql.fetchall(
            self.conn,
            """
            SELECT *
            FROM intents
            WHERE project_id = :project_id AND to_fact_id IS NULL
            ORDER BY created_at
            """,
            {"project_id": project_id},
        )
        if not rows:
            return []
        intent_ids = {row["id"] for row in rows}
        sources_by_intent = {
            intent_id: []
            for intent_id in intent_ids
        }
        for source in sql.fetchall(
            self.conn,
            """
            SELECT intent_id, fact_id
            FROM intent_sources
            WHERE project_id = :project_id
            ORDER BY intent_id, position, fact_id
            """,
            {"project_id": project_id},
        ):
            if source["intent_id"] in sources_by_intent:
                sources_by_intent[source["intent_id"]].append(source["fact_id"])
        return [_intent_projection(row, sources_by_intent) for row in rows]

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
