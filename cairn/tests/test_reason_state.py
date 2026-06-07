from __future__ import annotations

import os
os.environ.setdefault('CAIRN_JWT_SECRET', 'test-jwt-secret-do-not-use-in-prod-32bytes')
os.environ.setdefault('CAIRN_SECRETS_KEY', 'test-jwt-secret-do-not-use-in-prod-32bytes')

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class ReasonContractTests(unittest.TestCase):
    def test_blocked_payload_is_valid_reason_result(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        kind, data = validate_reason_payload(
            {
                "accepted": True,
                "data": {
                    "blocked": {
                        "from": ["f019"],
                        "description": "All high-value paths are exhausted.",
                        "retryable": False,
                    }
                },
            },
            open_intents_empty=True,
            max_intents=2,
        )
        self.assertEqual(kind, "blocked")
        self.assertEqual(data["from"], ["f019"])

    def test_empty_intents_with_no_open_intents_becomes_blocked(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        kind, data = validate_reason_payload(
            {"accepted": True, "data": {"intents": []}},
            open_intents_empty=True,
            max_intents=2,
        )
        self.assertEqual(kind, "blocked")
        self.assertIsInstance(data, dict)

    def test_empty_data_with_no_open_intents_becomes_blocked(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        kind, data = validate_reason_payload(
            {"accepted": True, "data": {}},
            open_intents_empty=True,
            max_intents=2,
        )
        self.assertEqual(kind, "blocked")
        self.assertIsInstance(data, dict)

    def test_empty_data_with_open_intents_remains_noop(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        kind, data = validate_reason_payload(
            {"accepted": True, "data": {}},
            open_intents_empty=False,
            max_intents=2,
        )
        self.assertEqual(kind, "noop")
        self.assertIsNone(data)


class ReasonStateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db

        db._db_path = None
        db.configure(Path(self.tmp.name))
        self.db = db

    def tearDown(self) -> None:
        self.db._db_path = None
        os.unlink(self.tmp.name)

    def _create_project(self) -> str:
        with self.db.get_conn() as conn:
            conn.execute(
                "INSERT INTO projects (id, title, status, created_at) VALUES ('proj_t', 'T', 'active', '2026-06-04T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO facts (id, project_id, description) VALUES ('origin', 'proj_t', 'o')"
            )
            conn.execute(
                "INSERT INTO facts (id, project_id, description) VALUES ('goal', 'proj_t', 'g')"
            )
        return "proj_t"

    def test_blocked_reason_state_consumes_same_trigger(self) -> None:
        from cairn.server.services import (
            finish_project_reason_or_409,
            reason_trigger_dispatch_blocker,
            reason_trigger_hash,
        )

        project_id = self._create_project()
        trigger = "facts:19->21"
        trigger_hash = reason_trigger_hash(trigger)
        with self.db.get_conn() as conn:
            finish_project_reason_or_409(
                conn,
                project_id,
                "codex",
                trigger,
                "2026-06-04T00:00:00Z",
                trigger_hash=trigger_hash,
                fact_count=21,
                hint_count=1,
                open_intent_count=0,
                outcome="blocked",
                error=None,
            )
            blocker = reason_trigger_dispatch_blocker(
                conn,
                project_id,
                trigger_hash,
                21,
                1,
                0,
                "2026-06-04T00:00:01Z",
            )
        self.assertIsNotNone(blocker)
        self.assertIn("already consumed", blocker)

    def test_failures_backoff_then_block_same_trigger(self) -> None:
        from cairn.server.services import (
            finish_project_reason_or_409,
            get_project_reason_state,
            reason_trigger_dispatch_blocker,
            reason_trigger_hash,
        )

        project_id = self._create_project()
        trigger = "facts:19->21"
        trigger_hash = reason_trigger_hash(trigger)
        with self.db.get_conn() as conn:
            finish_project_reason_or_409(
                conn,
                project_id,
                "codex",
                trigger,
                "2026-06-04T00:00:00Z",
                trigger_hash=trigger_hash,
                fact_count=21,
                hint_count=1,
                open_intent_count=0,
                outcome="timeout",
                error="timeout",
            )
            state = get_project_reason_state(conn, project_id)
            self.assertEqual(state.failure_count, 1)
            self.assertEqual(state.outcome, "timeout")
            self.assertIsNotNone(state.next_retry_at)
            blocker = reason_trigger_dispatch_blocker(
                conn,
                project_id,
                trigger_hash,
                21,
                1,
                0,
                "2026-06-04T00:00:01Z",
            )
            self.assertIn("backoff", blocker)

            finish_project_reason_or_409(
                conn,
                project_id,
                "codex",
                trigger,
                "2026-06-04T00:10:00Z",
                trigger_hash=trigger_hash,
                fact_count=21,
                hint_count=1,
                open_intent_count=0,
                outcome="timeout",
                error="timeout",
            )
            finish_project_reason_or_409(
                conn,
                project_id,
                "codex",
                trigger,
                "2026-06-04T00:20:00Z",
                trigger_hash=trigger_hash,
                fact_count=21,
                hint_count=1,
                open_intent_count=0,
                outcome="timeout",
                error="timeout",
            )
            state = get_project_reason_state(conn, project_id)
        self.assertEqual(state.outcome, "blocked")
        self.assertEqual(state.failure_count, 3)

    def test_superseded_reason_run_cannot_finish_active_claim(self) -> None:
        from fastapi import HTTPException

        from cairn.server.services import (
            claim_project_reason_or_409,
            finish_project_reason_or_409,
            reason_trigger_hash,
        )

        project_id = self._create_project()
        trigger = "facts:2->3"
        trigger_hash = reason_trigger_hash(trigger)
        with self.db.get_conn() as conn:
            claim_project_reason_or_409(
                conn,
                project_id,
                "codex",
                trigger,
                "2026-06-04T00:00:00Z",
                run_id="new-run",
                trigger_hash=trigger_hash,
                fact_count=3,
                hint_count=0,
                open_intent_count=0,
            )
            with self.assertRaises(HTTPException) as ctx:
                finish_project_reason_or_409(
                    conn,
                    project_id,
                    "codex",
                    trigger,
                    "2026-06-04T00:00:01Z",
                    run_id="old-run",
                    trigger_hash=trigger_hash,
                    fact_count=3,
                    hint_count=0,
                    open_intent_count=0,
                    outcome="blocked",
                    error=None,
                )
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
