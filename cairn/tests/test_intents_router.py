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
                INSERT INTO projects (id, title, status, created_at)
                VALUES (:id, :title, :status, :created_at)
                """,
                {
                    "id": "proj_t",
                    "title": "T",
                    "status": "active",
                    "created_at": "2026-06-06T00:00:00Z",
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
        from cairn.server.models_pkg.intents import ConcludeResponse, ReopenResponse, ReplayRunCreateResponse

        for model in (ConcludeResponse, ReopenResponse, ReplayRunCreateResponse):
            model.model_rebuild(raise_errors=True)

    def test_conclude_returns_response_model(self) -> None:
        from cairn.server.models_pkg.intents import ConcludeRequest, CreateIntentRequest
        from cairn.server.routers import intents

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


if __name__ == "__main__":
    unittest.main()
