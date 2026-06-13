from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class _Result:
    status_code = 201
    ok = True


class _FailResult:
    status_code = 0
    ok = False


class _FakeClient:
    def __init__(self, *, fail_events: bool = False):
        self.fail_events = fail_events
        self.created = 0
        self.event_batches: list[list[dict[str, str]]] = []
        self.finished = 0

    def create_llm_execution(self, *_args, **_kwargs):
        self.created += 1
        return _Result()

    def create_llm_events(self, *_args, **_kwargs):
        events = _args[-1] if _args else _kwargs["events"]
        self.event_batches.append(events)
        return _FailResult() if self.fail_events else _Result()

    def finish_llm_execution(self, *_args, **_kwargs):
        self.finished += 1
        return _Result()


class ExecutionReporterTests(unittest.TestCase):
    def _settings(self):
        from cairn.shared.config import ObservabilityConfig

        return ObservabilityConfig(flush_interval_ms=0, flush_max_bytes=1)

    def test_flush_enqueues_events_and_finish_drains(self) -> None:
        from cairn.dispatcher.observability.reporter import ExecutionReporter

        client = _FakeClient()
        reporter = ExecutionReporter(
            client,
            self._settings(),
            project_id="proj_001",
            intent_id="i001",
            task_type="bootstrap",
            worker="worker-a",
        )
        reporter.start()
        reporter.emit_output("bootstrap", "stdout", "hello")
        reporter.finish("completed")

        self.assertEqual(client.created, 1)
        self.assertEqual(client.finished, 1)
        contents = [event["content"] for batch in client.event_batches for event in batch]
        self.assertEqual(contents[0], "hello")
        self.assertIn("process_state=completed", contents[1])

    def test_failed_event_write_is_best_effort(self) -> None:
        from cairn.dispatcher.observability.reporter import ExecutionReporter

        client = _FakeClient(fail_events=True)
        reporter = ExecutionReporter(
            client,
            self._settings(),
            project_id="proj_001",
            intent_id="i001",
            task_type="bootstrap",
            worker="worker-a",
        )
        reporter.start()
        reporter.emit_output("bootstrap", "stdout", "hello")
        reporter.finish("failed", error_kind="test")

        self.assertEqual(client.finished, 1)


if __name__ == "__main__":
    unittest.main()
