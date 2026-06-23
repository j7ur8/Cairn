from __future__ import annotations

import json
import os

os.environ.setdefault('CAIRN_JWT_SECRET', 'test-jwt-secret-do-not-use-in-prod-32bytes')
os.environ.setdefault('CAIRN_SECRETS_KEY', 'test-jwt-secret-do-not-use-in-prod-32bytes')

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import reset_postgres_db


class _FakeReasonReporter:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, list[str] | None]] = []

    def emit_result(
        self,
        phase: str,
        content: str,
        *,
        produced_fact_id: str | None = None,
        created_intent_ids: list[str] | None = None,
    ) -> None:
        self.results.append((phase, content, created_intent_ids))

    def emit_error(self, phase: str, event_kind: str, content: str) -> None:
        pass


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

    def test_reason_write_event_reports_created_intents(self) -> None:
        from cairn.dispatcher.runtime.process import ProcessResult
        from cairn.dispatcher.tasks.reason_result import apply_reason_result

        reporter = _FakeReasonReporter()

        class FakeClient:
            def create_intent(self, project_id, from_ids, description, creator):
                self.args = (project_id, from_ids, description, creator)
                return SimpleNamespace(ok=True, status_code=200, data={"id": "i123"}, text="")

        client = FakeClient()
        payload = {
            "accepted": True,
            "data": {
                "intents": [
                    {
                        "from": ["f001"],
                        "description": "test access input parser path",
                    }
                ]
            },
        }
        result = apply_reason_result(
            client=client,
            driver=SimpleNamespace(extract_response_text=lambda stdout, stderr: stdout),
            project_id="proj_t",
            worker_name="reason",
            result=ProcessResult(
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
                timed_out=False,
            ),
            open_intents=[],
            max_intents=2,
            execute_ms=1,
            total_ms=1,
            reporter=reporter,
        )

        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.finish_outcome, "intents")
        phase, content, created_ids = reporter.results[-1]
        self.assertEqual(phase, "reason_write")
        self.assertEqual(created_ids, ["i123"])
        self.assertEqual(content, "created 1 intents")
        self.assertEqual(client.args, ("proj_t", ["f001"], "test access input parser path", "reason"))


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
                INSERT INTO projects (id, title, status, created_at, graph_revision, timeline_revision)
                VALUES ('proj_t', 'T', 'active', '2026-06-04T00:00:00Z', 1, 1)
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
        from cairn.server.application.reason_commands import claim_reason, finish_reason, reason_state
        from cairn.server.domain.reason import reason_trigger_hash
        from cairn.server.schemas import ReasonClaimRequest, ReasonFinishRequest

        project_id = self._create_project()
        trigger = "facts:19->21"
        trigger_hash = reason_trigger_hash(trigger)
        with self.db.session_scope() as conn:
            claim_reason(
                conn,
                project_id,
                ReasonClaimRequest(
                    worker="codex",
                    trigger=trigger,
                    run_id="run-1",
                    trigger_hash=trigger_hash,
                    fact_count=21,
                    hint_count=1,
                    open_intent_count=0,
                ),
            )
            finish_reason(
                conn,
                project_id,
                ReasonFinishRequest(
                    worker="codex",
                    trigger=trigger,
                    run_id="run-1",
                    trigger_hash=trigger_hash,
                    fact_count=21,
                    hint_count=1,
                    open_intent_count=0,
                    outcome="timeout",
                    error="timeout",
                ),
            )
            state = reason_state(conn, project_id)
            assert state is not None
            self.assertEqual(state.failure_count, 1)
            self.assertEqual(state.outcome, "timeout")
            self.assertIsNone(state.next_retry_at)

            claim_reason(
                conn,
                project_id,
                ReasonClaimRequest(
                    worker="codex",
                    trigger=trigger,
                    run_id="run-2",
                    trigger_hash=trigger_hash,
                    fact_count=21,
                    hint_count=1,
                    open_intent_count=0,
                ),
            )
            finish_reason(
                conn,
                project_id,
                ReasonFinishRequest(
                    worker="codex",
                    trigger=trigger,
                    run_id="run-2",
                    trigger_hash=trigger_hash,
                    fact_count=21,
                    hint_count=1,
                    open_intent_count=0,
                    outcome="timeout",
                    error="timeout",
                ),
            )
            claim_reason(
                conn,
                project_id,
                ReasonClaimRequest(
                    worker="codex",
                    trigger=trigger,
                    run_id="run-3",
                    trigger_hash=trigger_hash,
                    fact_count=21,
                    hint_count=1,
                    open_intent_count=0,
                ),
            )
            finish_reason(
                conn,
                project_id,
                ReasonFinishRequest(
                    worker="codex",
                    trigger=trigger,
                    run_id="run-3",
                    trigger_hash=trigger_hash,
                    fact_count=21,
                    hint_count=1,
                    open_intent_count=0,
                    outcome="timeout",
                    error="timeout",
                ),
            )
            state = reason_state(conn, project_id)
            assert state is not None
        self.assertEqual(state.outcome, "timeout")
        self.assertEqual(state.failure_count, 1)

    def test_superseded_reason_run_cannot_finish_active_claim(self) -> None:
        from cairn.server.application.reason_commands import claim_reason, finish_reason
        from cairn.server.domain.errors import DomainError
        from cairn.server.domain.reason import reason_trigger_hash
        from cairn.server.schemas import ReasonClaimRequest, ReasonFinishRequest

        project_id = self._create_project()
        trigger = "facts:2->3"
        trigger_hash = reason_trigger_hash(trigger)
        with self.db.session_scope() as conn:
            claim_reason(
                conn,
                project_id,
                ReasonClaimRequest(
                    worker="codex",
                    trigger=trigger,
                    run_id="new-run",
                    trigger_hash=trigger_hash,
                    fact_count=3,
                    hint_count=0,
                    open_intent_count=0,
                ),
            )
            with self.assertRaises(DomainError) as ctx:
                finish_reason(
                    conn,
                    project_id,
                    ReasonFinishRequest(
                        worker="codex",
                        trigger=trigger,
                        run_id="old-run",
                        trigger_hash=trigger_hash,
                        fact_count=3,
                        hint_count=0,
                        open_intent_count=0,
                        outcome="noop",
                        error=None,
                    ),
                )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_unclaimed_reason_cannot_finish(self) -> None:
        from cairn.server.application.reason_commands import finish_reason
        from cairn.server.domain.errors import DomainError
        from cairn.server.domain.reason import reason_trigger_hash
        from cairn.server.schemas import ReasonFinishRequest

        project_id = self._create_project()
        trigger = "facts:2->3"
        with self.db.session_scope() as conn:
            with self.assertRaises(DomainError) as ctx:
                finish_reason(
                    conn,
                    project_id,
                    ReasonFinishRequest(
                        worker="codex",
                        trigger=trigger,
                        run_id="missing-run",
                        trigger_hash=reason_trigger_hash(trigger),
                        fact_count=3,
                        hint_count=0,
                        open_intent_count=0,
                        outcome="noop",
                        error=None,
                    ),
                )
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
