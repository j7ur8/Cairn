from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")

from helpers import reset_postgres_db


class LeaseExpiryPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def _seed_project(self, conn, project_id: str, *, graph_revision: int = 1) -> None:
        from cairn.server.repositories.projects import ProjectRepository

        ProjectRepository(conn).insert_project(
            project_id=project_id,
            title=project_id,
            status="active",
            created_at="2026-06-06T00:00:00Z",
            graph_revision=graph_revision,
            timeline_revision=1,
            llm_hidden_event_kinds='["usage"]',
        )

    def _seed_open_intent(
        self,
        conn,
        *,
        project_id: str,
        intent_id: str,
        worker: str | None = None,
        last_heartbeat_at: str = "2026-06-06T00:00:00Z",
    ) -> None:
        from cairn.server.repositories.intents import IntentRepository

        intents = IntentRepository(conn)
        intents.insert_fact(project_id, "origin", "origin")
        intents.insert_open(
            project_id=project_id,
            intent_id=intent_id,
            source_fact_ids=["origin"],
            description="open intent",
            creator="seed",
            worker=worker,
            now=last_heartbeat_at,
        )

    def test_expire_workers_project_scope_without_expired_worker_does_not_error(self) -> None:
        from cairn.server.repositories.leases import LeaseRepository

        with self.db.session_scope() as conn:
            self._seed_project(conn, "proj_002")
            self._seed_open_intent(conn, project_id="proj_002", intent_id="i001")

        with self.db.session_scope() as conn:
            LeaseRepository(conn).expire_workers("proj_002")

    def test_claim_intent_project_scope_can_claim_unclaimed_intent(self) -> None:
        from cairn.server.application.intent_commands import claim_intent
        from cairn.server.schemas import HeartbeatRequest

        with self.db.session_scope() as conn:
            self._seed_project(conn, "proj_002")
            self._seed_open_intent(conn, project_id="proj_002", intent_id="i001")

        with self.db.session_scope() as conn:
            intent = claim_intent(conn, "proj_002", "i001", HeartbeatRequest(worker="worker_1"))

        self.assertEqual(intent.id, "i001")
        self.assertEqual(intent.worker, "worker_1")

    def test_expire_workers_clears_expired_project_scoped_worker_and_bumps_revision(self) -> None:
        from cairn.server.repositories import sql
        from cairn.server.repositories.leases import LeaseRepository

        with self.db.session_scope() as conn:
            self._seed_project(conn, "proj_expired", graph_revision=7)
            self._seed_open_intent(
                conn,
                project_id="proj_expired",
                intent_id="i_expired",
                worker="stale_worker",
                last_heartbeat_at="2000-01-01T00:00:00Z",
            )

        with self.db.session_scope() as conn:
            LeaseRepository(conn).expire_workers("proj_expired")

        with self.db.session_scope() as conn:
            intent = sql.fetchone(
                conn,
                "SELECT worker FROM intents WHERE project_id = :project_id AND id = :intent_id",
                {"project_id": "proj_expired", "intent_id": "i_expired"},
            )
            project = sql.fetchone(
                conn,
                "SELECT graph_revision FROM projects WHERE id = :project_id",
                {"project_id": "proj_expired"},
            )

        self.assertIsNotNone(intent)
        self.assertIsNone(intent["worker"])
        self.assertIsNotNone(project)
        self.assertEqual(project["graph_revision"], 8)

    def test_expire_reason_leases_project_scope_clears_reason_worker_and_bumps_revision(self) -> None:
        from cairn.server.repositories import sql
        from cairn.server.repositories.leases import LeaseRepository

        with self.db.session_scope() as conn:
            self._seed_project(conn, "proj_reason", graph_revision=3)
            sql.execute(
                conn,
                """
                UPDATE projects
                SET reason_worker = :worker,
                    reason_run_id = :run_id,
                    reason_trigger = :trigger,
                    reason_started_at = :started_at,
                    reason_last_heartbeat_at = :last_heartbeat_at
                WHERE id = :project_id
                """,
                {
                    "project_id": "proj_reason",
                    "worker": "reason_worker",
                    "run_id": "run_1",
                    "trigger": "manual",
                    "started_at": "2000-01-01T00:00:00Z",
                    "last_heartbeat_at": "2000-01-01T00:00:00Z",
                },
            )

        with self.db.session_scope() as conn:
            LeaseRepository(conn).expire_reason_leases("proj_reason")

        with self.db.session_scope() as conn:
            project = sql.fetchone(
                conn,
                """
                SELECT graph_revision, reason_worker, reason_run_id, reason_trigger,
                       reason_started_at, reason_last_heartbeat_at
                FROM projects
                WHERE id = :project_id
                """,
                {"project_id": "proj_reason"},
            )

        self.assertIsNotNone(project)
        self.assertEqual(project["graph_revision"], 4)
        self.assertIsNone(project["reason_worker"])
        self.assertIsNone(project["reason_run_id"])
        self.assertIsNone(project["reason_trigger"])
        self.assertIsNone(project["reason_started_at"])
        self.assertIsNone(project["reason_last_heartbeat_at"])

    def test_clear_project_reason_if_owner_matches_worker_and_nullable_run_id(self) -> None:
        from cairn.server.repositories import sql
        from cairn.server.repositories.reason import ReasonRepository

        with self.db.session_scope() as conn:
            self._seed_project(conn, "proj_reason")
            reason = ReasonRepository(conn)
            self.assertEqual(
                reason.claim_project_reason(
                    "proj_reason",
                    worker="reason_worker",
                    run_id="run_1",
                    trigger="manual",
                    now="2026-06-06T00:00:00Z",
                ),
                1,
            )
            self.assertEqual(
                reason.clear_project_reason_if_owner("proj_reason", worker="reason_worker", run_id="run_2"),
                0,
            )
            still_claimed = sql.fetchone(
                conn,
                "SELECT reason_worker, reason_run_id FROM projects WHERE id = 'proj_reason'",
            )
            self.assertEqual(still_claimed["reason_worker"], "reason_worker")
            self.assertEqual(still_claimed["reason_run_id"], "run_1")
            self.assertEqual(
                reason.clear_project_reason_if_owner("proj_reason", worker="reason_worker", run_id="run_1"),
                1,
            )
            cleared = sql.fetchone(
                conn,
                "SELECT reason_worker, reason_run_id FROM projects WHERE id = 'proj_reason'",
            )
            self.assertIsNone(cleared["reason_worker"])
            self.assertIsNone(cleared["reason_run_id"])

            self.assertEqual(
                reason.claim_project_reason(
                    "proj_reason",
                    worker="reason_worker",
                    run_id=None,
                    trigger="manual",
                    now="2026-06-06T00:00:01Z",
                ),
                1,
            )
            self.assertEqual(
                reason.clear_project_reason_if_owner("proj_reason", worker="reason_worker", run_id="run_1"),
                0,
            )
            self.assertEqual(
                reason.clear_project_reason_if_owner("proj_reason", worker="reason_worker", run_id=None),
                1,
            )


if __name__ == "__main__":
    unittest.main()
