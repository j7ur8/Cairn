"""Concurrency guard for the intent claim/conclude lease.

The dispatcher relies on ``IntentRepository.claim_open`` being mutually
exclusive: when several workers race to claim the same open intent, exactly
one must win. The implementation does not take an explicit ``FOR UPDATE``
lock — it relies on the conditional ``UPDATE ... WHERE worker IS NULL`` and
PostgreSQL's row-level locking under the default READ COMMITTED isolation:
the second writer blocks on the row, then re-evaluates the WHERE predicate
against the just-committed version and matches zero rows.

This test fixes that guarantee so a future change to the SQL, the isolation
level, or the session handling that breaks exclusivity fails loudly rather
than silently allowing double-claims. It is intentionally a real-database,
real-threads test: the property only holds against PostgreSQL semantics.
"""
from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")

from helpers import reset_postgres_db


class IntentClaimConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = reset_postgres_db()
        self._seed_open_intent()

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def _seed_open_intent(self) -> None:
        from cairn.server.repositories import sql

        with self.db.session_scope() as conn:
            sql.execute(
                conn,
                "INSERT INTO projects (id, title, status, created_at, graph_revision, timeline_revision) "
                "VALUES (:id, :title, :status, :created_at, :graph_revision, :timeline_revision)",
                {
                    "id": "proj_c",
                    "title": "C",
                    "status": "active",
                    "created_at": "2026-06-06T00:00:00Z",
                    "graph_revision": 1,
                    "timeline_revision": 1,
                },
            )
            sql.execute(
                conn,
                "INSERT INTO facts (id, project_id, description) VALUES (:id, :project_id, :description)",
                {"id": "origin", "project_id": "proj_c", "description": "origin"},
            )
            sql.execute(
                conn,
                """
                INSERT INTO intents (
                    id, project_id, to_fact_id, description, creator, worker,
                    last_heartbeat_at, created_at, concluded_at
                ) VALUES (
                    :id, :project_id, NULL, :description, :creator, NULL,
                    NULL, :created_at, NULL
                )
                """,
                {
                    "id": "intent_c",
                    "project_id": "proj_c",
                    "description": "race target",
                    "creator": "seed",
                    "created_at": "2026-06-06T00:00:00Z",
                },
            )

    def _claim(self, worker: str, start: threading.Barrier, results: list[tuple[str, int]]) -> None:
        from cairn.server.repositories.intents import IntentRepository

        # Each thread uses its own session/connection so the claims truly
        # contend at the database rather than serializing on one connection.
        start.wait()
        with self.db.session_scope() as conn:
            repo = IntentRepository(conn)
            rowcount = repo.claim_open("proj_c", "intent_c", worker, "2026-06-06T00:00:01Z")
            results.append((worker, rowcount))

    def test_concurrent_claims_yield_exactly_one_winner(self) -> None:
        workers = [f"worker_{i}" for i in range(8)]
        start = threading.Barrier(len(workers))
        results: list[tuple[str, int]] = []
        threads = [
            threading.Thread(target=self._claim, args=(w, start, results), daemon=True)
            for w in workers
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(results), len(workers), "every claim thread should finish")
        winners = [w for w, rc in results if rc == 1]
        losers = [w for w, rc in results if rc == 0]
        self.assertEqual(
            len(winners), 1,
            f"exactly one worker must win the claim, got winners={winners} results={results}",
        )
        self.assertEqual(len(losers), len(workers) - 1)

        # The DB must reflect the single winner as the owning worker.
        from cairn.server.repositories import sql

        with self.db.session_scope() as conn:
            row = sql.execute(
                conn,
                "SELECT worker FROM intents WHERE id = :id AND project_id = :p",
                {"id": "intent_c", "p": "proj_c"},
            ).fetchone()
        self.assertEqual(row[0], winners[0])

    def test_reclaim_by_same_worker_is_idempotent(self) -> None:
        """The owning worker re-claiming its own intent stays a no-conflict win."""
        from cairn.server.repositories.intents import IntentRepository

        with self.db.session_scope() as conn:
            repo = IntentRepository(conn)
            first = repo.claim_open("proj_c", "intent_c", "worker_a", "2026-06-06T00:00:01Z")
            second = repo.claim_open("proj_c", "intent_c", "worker_a", "2026-06-06T00:00:02Z")
        self.assertEqual(first, 1)
        self.assertEqual(second, 1, "same-worker reclaim should still match (worker = :worker branch)")

    def test_other_worker_cannot_steal_claimed_intent(self) -> None:
        from cairn.server.repositories.intents import IntentRepository

        with self.db.session_scope() as conn:
            repo = IntentRepository(conn)
            self.assertEqual(repo.claim_open("proj_c", "intent_c", "worker_a", "2026-06-06T00:00:01Z"), 1)
        with self.db.session_scope() as conn:
            repo = IntentRepository(conn)
            stolen = repo.claim_open("proj_c", "intent_c", "worker_b", "2026-06-06T00:00:02Z")
        self.assertEqual(stolen, 0, "a different worker must not be able to claim an owned intent")


if __name__ == "__main__":
    unittest.main()
