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


class IntentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def _create_project(self) -> None:
        from cairn.server.repositories import sql

        with self.db.session_scope() as conn:
            sql.execute(
                conn,
                """
                INSERT INTO projects (id, title, status, created_at, graph_revision, timeline_revision)
                VALUES (:id, :title, :status, :created_at, :graph_revision, :timeline_revision)
                """,
                {
                    "id": "proj_t",
                    "title": "T",
                    "status": "active",
                    "created_at": "2026-06-06T00:00:00Z",
                    "graph_revision": 1,
                    "timeline_revision": 1,
                },
            )
            sql.execute(
                conn,
                """
                INSERT INTO facts (id, project_id, description)
                VALUES (:id, :project_id, :description)
                """,
                {"id": "origin", "project_id": "proj_t", "description": "origin"},
            )

    def test_cross_module_response_models_rebuild(self) -> None:
        from cairn.server.schemas import ConcludeResponse, ReopenResponse, ReplayRunCreateResponse

        for model in (ConcludeResponse, ReopenResponse, ReplayRunCreateResponse):
            model.model_rebuild(raise_errors=True)

    def test_conclude_returns_response_model(self) -> None:
        from cairn.server.routers import intents
        from cairn.server.schemas import ConcludeRequest, CreateIntentRequest

        self._create_project()
        created = intents.create_intent(
            "proj_t",
            CreateIntentRequest(
                **{
                    "from": ["origin"],
                    "description": "investigate origin",
                    "creator": "worker_a",
                    "worker": "worker_a",
                }
            ),
        )

        response = intents.conclude(
            "proj_t",
            created.id,
            ConcludeRequest(worker="worker_a", description="confirmed fact"),
        )

        self.assertEqual(response.fact.description, "confirmed fact")
        self.assertEqual(response.intent.to, response.fact.id)
        self.assertEqual(response.intent.id, created.id)

    def test_claim_and_heartbeat_are_separate(self) -> None:
        from cairn.server.domain.errors import DomainError
        from cairn.server.routers import intents
        from cairn.server.schemas import CreateIntentRequest, HeartbeatRequest

        self._create_project()
        created = intents.create_intent(
            "proj_t",
            CreateIntentRequest(
                **{
                    "from": ["origin"],
                    "description": "investigate origin",
                    "creator": "worker_a",
                    "worker": None,
                }
            ),
        )

        with self.assertRaises(DomainError) as heartbeat_ctx:
            intents.heartbeat("proj_t", created.id, HeartbeatRequest(worker="worker_a"))
        self.assertEqual(heartbeat_ctx.exception.status_code, 409)

        claimed = intents.claim("proj_t", created.id, HeartbeatRequest(worker="worker_a"))
        self.assertEqual(claimed.worker, "worker_a")

        renewed = intents.heartbeat("proj_t", created.id, HeartbeatRequest(worker="worker_a"))
        self.assertEqual(renewed.worker, "worker_a")

    def test_create_intent_returns_core_model(self) -> None:
        from cairn.server.routers import intents
        from cairn.server.schemas import CreateIntentRequest

        self._create_project()
        created = intents.create_intent(
            "proj_t",
            CreateIntentRequest(
                **{
                    "from": ["origin"],
                    "description": "investigate high value path",
                    "creator": "worker_a",
                }
            ),
        )

        self.assertEqual(created.description, "investigate high value path")
        self.assertEqual(created.creator, "worker_a")
        self.assertIsNone(created.worker)

    def test_project_reads_do_not_expire_leases(self) -> None:
        from cairn.server.routers import projects

        self._create_project()
        self.assertFalse(hasattr(projects, "expire_workers"))
        projects.list_projects()
        projects.get_project("proj_t")

    def test_export_read_does_not_expire_leases(self) -> None:
        from unittest.mock import patch

        from cairn.server.application import export

        self._create_project()
        with (
            patch("cairn.server.repositories.export.require_project") as get_project,
            patch("cairn.server.repositories.leases.LeaseRepository.expire_workers") as expire_workers,
            patch("cairn.server.repositories.leases.LeaseRepository.expire_reason_leases") as expire_reason_leases,
        ):
            with self.db.session_scope() as conn:
                export.export_project_yaml(conn, "proj_t")

        get_project.assert_called_once()
        expire_workers.assert_not_called()
        expire_reason_leases.assert_not_called()


if __name__ == "__main__":
    unittest.main()
