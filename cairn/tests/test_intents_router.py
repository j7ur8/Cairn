from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class IntentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db

        db._db_path = None
        db.close_thread_conn()
        db.configure(Path(self.tmp.name))
        self.db = db

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db._db_path = None
        os.unlink(self.tmp.name)

    def _create_project(self) -> None:
        with self.db.get_conn() as conn:
            conn.execute(
                "INSERT INTO projects (id, title, status, created_at) VALUES (?, ?, ?, ?)",
                ("proj_t", "T", "active", "2026-06-06T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
                ("origin", "proj_t", "origin"),
            )

    def test_cross_module_response_models_rebuild(self) -> None:
        from cairn.server.models import ConcludeResponse, ReopenResponse, ReplayRunCreateResponse

        for model in (ConcludeResponse, ReopenResponse, ReplayRunCreateResponse):
            model.model_rebuild(raise_errors=True)

    def test_conclude_returns_response_model(self) -> None:
        from cairn.server.models import ConcludeRequest, CreateIntentRequest
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
