from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import reset_postgres_db


def _explain_json(conn, query: str, params: dict[str, object] | None = None) -> object:
    from sqlalchemy import text

    value = conn.execute(text(f"EXPLAIN (FORMAT JSON) {query}"), dict(params or {})).scalar_one()
    if isinstance(value, str):
        return json.loads(value)
    return value


def _plan_text(plan: object) -> str:
    return json.dumps(plan, sort_keys=True)


class HotQueryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        from cairn.server import db

        reset_postgres_db()
        self.db = db
        self.conn_cm = db.session_scope()
        self.conn = self.conn_cm.__enter__()

    def tearDown(self) -> None:
        self.conn_cm.__exit__(None, None, None)
        self.db.reset_for_tests()

    def _insert_project(self, project_id: str, created_at: str = "2026-06-01T00:00:00Z") -> None:
        from cairn.server.repositories import sql

        sql.execute(
            self.conn,
            """
            INSERT INTO projects (id, title, status, created_at)
            VALUES (:id, :title, 'active', :created_at)
            """,
            {"id": project_id, "title": project_id, "created_at": created_at},
        )

    def _insert_fact(self, project_id: str, fact_id: str) -> None:
        from cairn.server.repositories import sql

        sql.execute(
            self.conn,
            """
            INSERT INTO facts (id, project_id, description)
            VALUES (:id, :project_id, :description)
            """,
            {"id": fact_id, "project_id": project_id, "description": fact_id},
        )

    def _insert_intent(
        self,
        project_id: str,
        intent_id: str,
        *,
        to_fact_id: str | None,
        worker: str | None,
        concluded_at: str | None,
        sources: list[str] | None = None,
    ) -> None:
        from cairn.server.repositories import sql

        sql.execute(
            self.conn,
            """
            INSERT INTO intents (
                id, project_id, to_fact_id, description, creator, worker,
                last_heartbeat_at, created_at, concluded_at
            ) VALUES (
                :id, :project_id, :to_fact_id, :description, 'test', :worker,
                :last_heartbeat_at, '2026-06-01T00:00:00Z', :concluded_at
            )
            """,
            {
                "id": intent_id,
                "project_id": project_id,
                "to_fact_id": to_fact_id,
                "description": intent_id,
                "worker": worker,
                "last_heartbeat_at": "2026-06-01T00:00:00Z" if worker else None,
                "concluded_at": concluded_at,
            },
        )
        for position, fact_id in enumerate(sources or []):
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

    def test_project_lists_return_same_aggregate_counts(self) -> None:
        from cairn.server.repositories import sql
        from cairn.server.repositories.projects import ProjectRepository

        self._insert_project("proj_a", "2026-06-01T00:00:00Z")
        self._insert_project("proj_b", "2026-06-02T00:00:00Z")
        self._insert_fact("proj_a", "origin")
        self._insert_fact("proj_a", "fact_a")
        self._insert_fact("proj_b", "origin")
        self._insert_intent("proj_a", "intent_claimed", to_fact_id=None, worker="worker-a", concluded_at=None)
        self._insert_intent("proj_a", "intent_unclaimed", to_fact_id=None, worker=None, concluded_at=None)
        self._insert_intent(
            "proj_a",
            "intent_done",
            to_fact_id="fact_a",
            worker="worker-a",
            concluded_at="2026-06-01T01:00:00Z",
        )
        sql.execute(
            self.conn,
            """
            INSERT INTO hints (id, project_id, content, creator, created_at)
            VALUES ('hint_a', 'proj_a', 'hint', 'test', '2026-06-01T00:00:00Z')
            """,
        )
        sql.execute(
            self.conn,
            """
            INSERT INTO project_execution_configs (project_id, version, created_at, updated_at)
            VALUES ('proj_a', 7, '2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z')
            """,
        )

        rows = ProjectRepository(self.conn).list_with_counts()
        by_id = {row["id"]: row for row in rows}
        self.assertEqual([row["id"] for row in rows], ["proj_a", "proj_b"])
        self.assertEqual(by_id["proj_a"]["fact_count"], 2)
        self.assertEqual(by_id["proj_a"]["intent_count"], 3)
        self.assertEqual(by_id["proj_a"]["working_intent_count"], 1)
        self.assertEqual(by_id["proj_a"]["unclaimed_intent_count"], 1)
        self.assertEqual(by_id["proj_a"]["hint_count"], 1)
        self.assertEqual(by_id["proj_b"]["fact_count"], 1)
        self.assertEqual(by_id["proj_b"]["intent_count"], 0)
        self.assertEqual(by_id["proj_b"]["hint_count"], 0)

        work_rows = {row["id"]: row for row in ProjectRepository(self.conn).list_work_summaries()}
        self.assertEqual(work_rows["proj_a"]["config_version"], 7)
        self.assertEqual(work_rows["proj_b"]["config_version"], 0)
        self.assertEqual(work_rows["proj_a"]["working_intent_count"], 1)
        self.assertEqual(work_rows["proj_b"]["unclaimed_intent_count"], 0)

    def test_execution_list_aggregates_only_paged_execution_events(self) -> None:
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution, list_executions
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_execs"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id="exec_old", intent_id=None, task_type="reason", worker="worker-a"),
        )
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id="exec_new", intent_id=None, task_type="reason", worker="worker-a"),
        )
        from cairn.server.repositories import sql

        sql.execute(
            self.conn,
            """
            UPDATE llm_executions
            SET started_at = CASE
                WHEN id = 'exec_old' THEN '2026-06-01T00:00:00Z'
                WHEN id = 'exec_new' THEN '2026-06-02T00:00:00Z'
                ELSE started_at
            END
            WHERE id IN ('exec_old', 'exec_new')
            """,
        )
        append_event(
            self.conn,
            project_id,
            "exec_old",
            CreateEventRequest(phase="reason", event_kind="stdout", stream="stdout", content="old"),
            ObservabilitySettings(),
        )
        append_event(
            self.conn,
            project_id,
            "exec_new",
            CreateEventRequest(phase="reason", event_kind="stdout", stream="stdout", content="new-event"),
            ObservabilitySettings(),
        )

        rows = list_executions(self.conn, project_id, limit=1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, "exec_new")
        self.assertEqual(rows[0].event_count, 1)
        self.assertGreaterEqual(rows[0].bytes_written, len("new-event"))
        self.assertIsNotNone(rows[0].last_event_at)

    def test_event_view_reports_usage_only_as_hidden_event_stats(self) -> None:
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )
        from cairn.server.observability.view_service import list_event_view

        project_id = "proj_view_counts"
        execution_id = "exec_view_counts"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id=None, task_type="reason", worker="worker-a"),
        )
        append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(
                phase="reason",
                event_kind="usage",
                stream="system",
                content='{"estimated_tokens":1}',
            ),
            ObservabilitySettings(),
        )
        append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(
                phase="reason",
                event_kind="usage",
                stream="system",
                content='{"estimated_tokens":2}',
            ),
            ObservabilitySettings(),
        )
        append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(phase="reason", event_kind="agent_message", stream="result", content="visible"),
            ObservabilitySettings(),
        )

        view = list_event_view(
            self.conn,
            project_id,
            execution_id=execution_id,
            limit=10,
            event_kinds=["agent_message"],
        )

        self.assertEqual(view.stats.hidden_by_kind, {"usage": 2})
        self.assertFalse(hasattr(view, "activity"))
        self.assertEqual([event.event_kind for event in view.primary_events], ["agent_message"])

    def test_replay_route_loads_reachable_project_subgraph(self) -> None:
        from cairn.server.application.replay.route_extractor import extract_replay_route
        from cairn.server.repositories.replay import ReplayRepository

        self._insert_project("proj_replay")
        self._insert_intent(
            "proj_replay",
            "intent_a",
            to_fact_id="fact_a",
            worker="worker-a",
            concluded_at="2026-06-01T00:00:00Z",
            sources=["origin"],
        )
        self._insert_intent(
            "proj_replay",
            "intent_b",
            to_fact_id="fact_b",
            worker="worker-a",
            concluded_at="2026-06-01T00:00:00Z",
            sources=["fact_a"],
        )
        for index in range(25):
            self._insert_intent(
                "proj_replay",
                f"intent_unreachable_{index}",
                to_fact_id=f"fact_unreachable_{index}",
                worker="worker-a",
                concluded_at="2026-06-01T00:00:00Z",
                sources=["origin"],
            )

        route = extract_replay_route(self.conn, "proj_replay", ["fact_b", "fact_b"])

        self.assertEqual([intent["id"] for intent in route], ["intent_a", "intent_b"])
        graph = ReplayRepository(self.conn).route_graph_for_facts("proj_replay", ["fact_b"])
        self.assertEqual(set(graph[0]), {"intent_a", "intent_b"})
        self.assertEqual(set(graph[2]), {"fact_a", "fact_b"})

    def test_replay_route_preserves_missing_and_cycle_errors(self) -> None:
        from cairn.server.application.replay.route_extractor import extract_replay_route
        from cairn.server.domain.errors import ConflictError

        self._insert_project("proj_missing")
        with self.assertRaisesRegex(ConflictError, "Fact missing has no producing intent"):
            extract_replay_route(self.conn, "proj_missing", ["missing"])

        self._insert_project("proj_cycle")
        self._insert_intent(
            "proj_cycle",
            "intent_a",
            to_fact_id="fact_a",
            worker="worker-a",
            concluded_at="2026-06-01T00:00:00Z",
            sources=["fact_b"],
        )
        self._insert_intent(
            "proj_cycle",
            "intent_b",
            to_fact_id="fact_b",
            worker="worker-a",
            concluded_at="2026-06-01T00:00:00Z",
            sources=["fact_a"],
        )
        with self.assertRaisesRegex(ConflictError, "Replay route contains a cycle"):
            extract_replay_route(self.conn, "proj_cycle", ["fact_a"])

    def test_replay_route_preserves_multiple_producer_errors(self) -> None:
        from cairn.server.application.replay import route_extractor
        from cairn.server.domain.errors import ConflictError

        class FakeReplayRepository:
            def __init__(self, conn):
                pass

            def route_graph_for_facts(self, project_id, seed_fact_ids):
                intent_a = {"id": "intent_a", "to_fact_id": "fact_a"}
                intent_b = {"id": "intent_b", "to_fact_id": "fact_a"}
                return (
                    {"intent_a": intent_a, "intent_b": intent_b},
                    {"intent_a": ["origin"], "intent_b": ["origin"]},
                    {"fact_a": [intent_a, intent_b]},
                )

        with patch.object(route_extractor, "ReplayRepository", FakeReplayRepository):
            with self.assertRaisesRegex(ConflictError, "Fact fact_a has multiple producing intents"):
                route_extractor.extract_replay_route(object(), "proj_replay", ["fact_a"])

    def test_retention_deletes_old_execution_events_in_batch(self) -> None:
        from cairn.server.observability.retention import prune_older_than
        from cairn.server.repositories import sql

        for execution_id, started_at in (
            ("exec_old", "2026-06-01T00:00:00Z"),
            ("exec_new", "2026-06-03T00:00:00Z"),
        ):
            sql.execute(
                self.conn,
                """
                INSERT INTO llm_executions (
                    id, project_id, worker, task_type, process_state, started_at
                ) VALUES (
                    :id, 'proj_retention', 'worker-a', 'reason', 'completed', :started_at
                )
                """,
                {"id": execution_id, "started_at": started_at},
            )
            sql.execute(
                self.conn,
                """
                INSERT INTO llm_execution_events (
                    execution_id, project_id, task_type, worker, phase,
                    event_kind, stream, content, created_at
                ) VALUES (
                    :execution_id, 'proj_retention', 'reason', 'worker-a', 'reason',
                    'stdout', 'stdout', :content, :started_at
                )
                """,
                {"execution_id": execution_id, "content": execution_id, "started_at": started_at},
            )

        deleted = prune_older_than(self.conn, "2026-06-02T00:00:00Z")

        self.assertEqual(deleted, 1)
        executions = sql.fetchall(self.conn, "SELECT id FROM llm_executions ORDER BY id")
        events = sql.fetchall(self.conn, "SELECT execution_id FROM llm_execution_events ORDER BY execution_id")
        self.assertEqual([row["id"] for row in executions], ["exec_new"])
        self.assertEqual([row["execution_id"] for row in events], ["exec_new"])

    def test_retention_prune_does_not_fetch_old_execution_ids(self) -> None:
        from cairn.server.observability import retention_repository
        from cairn.server.observability.retention import prune_older_than

        with patch.object(
            retention_repository.LlmRetentionRepository,
            "execution_ids_older_than",
            side_effect=AssertionError("old id prefetch path should not run"),
        ):
            deleted = prune_older_than(self.conn, "2026-06-02T00:00:00Z")
        self.assertEqual(deleted, 0)

    def test_project_list_and_work_summary_plans_have_no_subplans(self) -> None:
        from cairn.server.repositories.projects import ProjectRepository

        self._insert_project("proj_plan")
        repo = ProjectRepository(self.conn)
        plan = _plan_text(_explain_json(self.conn, f"""
            SELECT p.*,
                {repo._count_selects()}
            FROM projects p
            {repo._count_joins()}
            ORDER BY p.created_at
        """))
        self.assertNotIn("SubPlan", plan)

        work_plan = _plan_text(_explain_json(self.conn, f"""
            SELECT p.*,
                COALESCE(pec.version, 0) AS config_version,
                {repo._count_selects()}
            FROM projects p
            LEFT JOIN project_execution_configs pec ON pec.project_id = p.id
            {repo._count_joins()}
            ORDER BY p.created_at
        """))
        self.assertNotIn("SubPlan", work_plan)

    def test_execution_list_plan_aggregates_after_paging_cte(self) -> None:
        query = """
            WITH paged AS (
                SELECT *
                FROM llm_executions
                WHERE project_id = :project_id
                ORDER BY started_at DESC, id DESC
                LIMIT :limit
            ),
            event_stats AS (
                SELECT
                    ev.execution_id,
                    MAX(ev.created_at) AS last_event_at,
                    COUNT(*) AS event_count,
                    COALESCE(SUM(LENGTH(ev.content)), 0) AS bytes_written
                FROM llm_execution_events ev
                WHERE ev.execution_id IN (SELECT id FROM paged)
                GROUP BY ev.execution_id
            )
            SELECT
                e.id,
                e.project_id,
                e.intent_id,
                e.task_type,
                e.worker,
                e.process_state,
                e.started_at,
                e.ended_at,
                COALESCE(event_stats.last_event_at, e.last_event_at) AS last_event_at,
                GREATEST(
                    e.event_count::bigint,
                    COALESCE(event_stats.event_count, 0)::bigint
                ) AS event_count,
                GREATEST(
                    e.bytes_written::bigint,
                    COALESCE(event_stats.bytes_written, 0)::bigint
                ) AS bytes_written,
                e.returncode,
                e.timed_out,
                e.error_kind,
                e.produced_fact_id,
                e.created_intent_ids
            FROM paged e
            LEFT JOIN event_stats ON event_stats.execution_id = e.id
            ORDER BY e.started_at DESC, e.id DESC
        """
        plan = _plan_text(_explain_json(self.conn, query, {"project_id": "proj_execs", "limit": 10}))
        self.assertIn("CTE", plan)
        self.assertNotIn("SubPlan", plan)

    def test_retention_delete_plan_uses_join_delete(self) -> None:
        plan = _plan_text(_explain_json(self.conn, """
            DELETE FROM llm_execution_events ev
            USING llm_executions e
            WHERE ev.execution_id = e.id
              AND e.started_at < :cutoff
        """, {"cutoff": "1900-01-01T00:00:00Z"}))
        self.assertIn("ModifyTable", plan)
        self.assertIn("Join", plan)


if __name__ == "__main__":
    unittest.main()
