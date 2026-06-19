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


class HintsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def _create_project(self, status: str = "active") -> None:
        from cairn.server.repositories import sql

        with self.db.session_scope() as conn:
            sql.execute(
                conn,
                """
                INSERT INTO projects (id, title, status, created_at, graph_revision, timeline_revision)
                VALUES (:id, :title, :status, :created_at, :graph_revision, :timeline_revision)
                """,
                {
                    "id": "proj_h",
                    "title": "H",
                    "status": status,
                    "created_at": "2026-06-06T00:00:00Z",
                    "graph_revision": 1,
                    "timeline_revision": 1,
                },
            )

    def test_create_hint_persists_and_returns_model(self) -> None:
        from cairn.server.routers import hints
        from cairn.server.schemas import CreateHintRequest

        self._create_project()
        result = hints.create_hint(
            "proj_h",
            CreateHintRequest(content="check the login flow", creator="worker_a"),
        )
        self.assertEqual(result.content, "check the login flow")
        self.assertEqual(result.creator, "worker_a")
        self.assertTrue(result.id)

        # Hint id should be unique/monotonic for a second insert.
        second = hints.create_hint(
            "proj_h",
            CreateHintRequest(content="also check logout", creator="worker_b"),
        )
        self.assertNotEqual(result.id, second.id)

    def test_create_hint_unknown_project_raises_not_found(self) -> None:
        from cairn.server.domain.errors import NotFoundError
        from cairn.server.routers import hints
        from cairn.server.schemas import CreateHintRequest

        with self.assertRaises(NotFoundError):
            hints.create_hint(
                "proj_missing",
                CreateHintRequest(content="x", creator="worker_a"),
            )

    def test_create_hint_blocked_on_non_writable_status(self) -> None:
        from cairn.server.domain.errors import ForbiddenError
        from cairn.server.routers import hints
        from cairn.server.schemas import CreateHintRequest

        self._create_project(status="deleted")
        with self.assertRaises(ForbiddenError):
            hints.create_hint(
                "proj_h",
                CreateHintRequest(content="x", creator="worker_a"),
            )

    def test_create_hint_rejects_blank_content(self) -> None:
        from pydantic import ValidationError

        from cairn.server.schemas import CreateHintRequest

        with self.assertRaises(ValidationError):
            CreateHintRequest(content="   ", creator="worker_a")


if __name__ == "__main__":
    unittest.main()
