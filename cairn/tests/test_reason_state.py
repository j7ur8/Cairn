from __future__ import annotations

import os
os.environ.setdefault('CAIRN_JWT_SECRET', 'test-jwt-secret-do-not-use-in-prod-32bytes')
os.environ.setdefault('CAIRN_SECRETS_KEY', 'test-jwt-secret-do-not-use-in-prod-32bytes')

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import reset_postgres_db


class ReasonContractTests(unittest.TestCase):
    def test_blocked_payload_is_rejected(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        with self.assertRaises(ValueError):
            validate_reason_payload(
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

    def test_empty_intents_with_no_open_intents_is_invalid(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        with self.assertRaises(ValueError):
            validate_reason_payload(
                {"accepted": True, "data": {"intents": []}},
                open_intents_empty=True,
                max_intents=2,
            )

    def test_empty_data_with_no_open_intents_is_invalid(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        with self.assertRaises(ValueError):
            validate_reason_payload(
                {"accepted": True, "data": {}},
                open_intents_empty=True,
                max_intents=2,
            )

    def test_empty_data_with_open_intents_remains_noop(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        kind, data = validate_reason_payload(
            {"accepted": True, "data": {}},
            open_intents_empty=False,
            max_intents=2,
        )
        self.assertEqual(kind, "noop")
        self.assertIsNone(data)

    def test_singular_intent_is_accepted(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        kind, data = validate_reason_payload(
            {
                "accepted": True,
                "data": {"intent": {"from": ["f001"], "description": "try another path"}},
            },
            open_intents_empty=True,
            max_intents=2,
        )
        self.assertEqual(kind, "intents")
        self.assertEqual(data, [{"from": ["f001"], "description": "try another path"}])


class ReasonStateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def _create_project(self) -> str:
        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            sql.execute(
                conn,
                """
                INSERT INTO projects (id, title, status, created_at)
                VALUES ('proj_t', 'T', 'active', '2026-06-04T00:00:00Z')
                """,
            )
            sql.execute(
                conn,
                "INSERT INTO facts (id, project_id, description) VALUES ('origin', 'proj_t', 'o')",
            )
            sql.execute(
                conn,
                "INSERT INTO facts (id, project_id, description) VALUES ('goal', 'proj_t', 'g')",
            )
        return "proj_t"

    def test_failures_are_recorded_without_blocking_outcome(self) -> None:
        from cairn.server.services import (
            finish_project_reason_or_409,
            get_project_reason_state,
            reason_trigger_hash,
        )

        project_id = self._create_project()
        trigger = "facts:19->21"
        trigger_hash = reason_trigger_hash(trigger)
        with self.db.session_scope() as conn:
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
            self.assertIsNone(state.next_retry_at)

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
        self.assertEqual(state.outcome, "timeout")
        self.assertEqual(state.failure_count, 1)

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
        with self.db.session_scope() as conn:
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
                    outcome="noop",
                    error=None,
                )
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
