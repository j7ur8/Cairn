from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql


class ReplayRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def get_run_by_replay_project(self, project_id: str) -> Any | None:
        return sql.fetchone(
            self.conn,
            """
            SELECT *
            FROM replay_runs
            WHERE replay_project_id = :project_id
            """,
            {"project_id": project_id},
        )

    def insert_run(
        self,
        *,
        run_id: str,
        source_project_id: str,
        replay_project_id: str,
        completion_description: str,
        created_at: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO replay_runs (
                id, source_project_id, replay_project_id, status,
                completion_description, created_at
            ) VALUES (
                :id, :source_project_id, :replay_project_id, 'active',
                :completion_description, :created_at
            )
            """,
            {
                "id": run_id,
                "source_project_id": source_project_id,
                "replay_project_id": replay_project_id,
                "completion_description": completion_description,
                "created_at": created_at,
            },
        )

    def map_fact(self, *, run_id: str, source_fact_id: str, replay_fact_id: str) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO replay_fact_map (run_id, source_fact_id, replay_fact_id)
            VALUES (:run_id, :source_fact_id, :replay_fact_id)
            ON CONFLICT (run_id, source_fact_id) DO UPDATE
            SET replay_fact_id = EXCLUDED.replay_fact_id
            """,
            {
                "run_id": run_id,
                "source_fact_id": source_fact_id,
                "replay_fact_id": replay_fact_id,
            },
        )

    def mapped_fact_id(self, run_id: str, source_fact_id: str) -> str | None:
        row = sql.fetchone(
            self.conn,
            """
            SELECT replay_fact_id
            FROM replay_fact_map
            WHERE run_id = :run_id AND source_fact_id = :source_fact_id
            """,
            {"run_id": run_id, "source_fact_id": source_fact_id},
        )
        return row["replay_fact_id"] if row is not None else None

    def insert_step(
        self,
        *,
        run_id: str,
        step_index: int,
        source_intent_id: str,
        source_to_fact_id: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO replay_steps (
                run_id, step_index, source_intent_id, source_to_fact_id, status
            ) VALUES (
                :run_id, :step_index, :source_intent_id, :source_to_fact_id, 'pending'
            )
            """,
            {
                "run_id": run_id,
                "step_index": step_index,
                "source_intent_id": source_intent_id,
                "source_to_fact_id": source_to_fact_id,
            },
        )

    def steps(self, run_id: str) -> list[Any]:
        return sql.fetchall(
            self.conn,
            """
            SELECT *
            FROM replay_steps
            WHERE run_id = :run_id
            ORDER BY step_index
            """,
            {"run_id": run_id},
        )

    def created_steps_with_replay_intent(self, run_id: str) -> list[Any]:
        return sql.fetchall(
            self.conn,
            """
            SELECT *
            FROM replay_steps
            WHERE run_id = :run_id AND status = 'created' AND replay_intent_id IS NOT NULL
            ORDER BY step_index
            """,
            {"run_id": run_id},
        )

    def mark_step_created(
        self,
        *,
        run_id: str,
        step_index: int,
        replay_intent_id: str,
        created_at: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE replay_steps
            SET status = 'created', replay_intent_id = :replay_intent_id, created_at = :created_at
            WHERE run_id = :run_id AND step_index = :step_index
            """,
            {
                "replay_intent_id": replay_intent_id,
                "created_at": created_at,
                "run_id": run_id,
                "step_index": step_index,
            },
        )

    def mark_step_concluded(
        self,
        *,
        run_id: str,
        step_index: int,
        concluded_at: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE replay_steps
            SET status = 'concluded', concluded_at = :concluded_at
            WHERE run_id = :run_id AND step_index = :step_index
            """,
            {"concluded_at": concluded_at, "run_id": run_id, "step_index": step_index},
        )

    def producing_intents_for_fact(self, project_id: str, fact_id: str) -> list[Any]:
        return sql.fetchall(
            self.conn,
            """
            SELECT *
            FROM intents
            WHERE project_id = :project_id AND to_fact_id = :fact_id
            """,
            {"project_id": project_id, "fact_id": fact_id},
        )

    def get_intent(self, project_id: str, intent_id: str) -> Any | None:
        return sql.fetchone(
            self.conn,
            """
            SELECT *
            FROM intents
            WHERE project_id = :project_id AND id = :intent_id
            """,
            {"project_id": project_id, "intent_id": intent_id},
        )

    def fact_description(self, project_id: str, fact_id: str) -> str:
        row = sql.fetchone(
            self.conn,
            "SELECT description FROM facts WHERE project_id = :project_id AND id = :fact_id",
            {"project_id": project_id, "fact_id": fact_id},
        )
        return row["description"] if row is not None else ""

    def mark_run_completed(self, run_id: str, completed_at: str) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE replay_runs
            SET status = 'completed', completed_at = COALESCE(completed_at, :completed_at)
            WHERE id = :run_id
            """,
            {"completed_at": completed_at, "run_id": run_id},
        )
