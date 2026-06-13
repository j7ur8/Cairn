"""Tests for the structured logging / metrics / trace-id stack."""
from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import TempYamlConfig, reset_postgres_db


class TraceIdTests(unittest.TestCase):
    def test_default_is_none(self) -> None:
        from cairn.observability import trace
        # Reset in case a prior test left it bound.
        trace.trace_id_var.set(None)
        self.assertIsNone(trace.get_trace_id())

    def test_new_trace_id_sets_value(self) -> None:
        from cairn.observability import trace
        tid = trace.new_trace_id()
        self.assertEqual(len(tid), 32)
        self.assertEqual(trace.get_trace_id(), tid)

    def test_set_and_reset(self) -> None:
        from cairn.observability import trace
        trace.trace_id_var.set(None)
        token = trace.set_trace_id("abc")
        self.assertEqual(trace.get_trace_id(), "abc")
        trace.reset_trace_id(token)
        self.assertIsNone(trace.get_trace_id())


class JsonFormatterTests(unittest.TestCase):
    def test_emits_json_with_trace_id(self) -> None:
        from cairn.observability.logging import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="cairn.test", level=logging.INFO, pathname="x", lineno=1,
            msg="hello %s", args=("world",), exc_info=None,
        )
        record.trace_id = "deadbeef"
        out = formatter.format(record)
        payload = json.loads(out)
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "cairn.test")
        self.assertEqual(payload["message"], "hello world")
        self.assertEqual(payload["trace_id"], "deadbeef")

    def test_extra_fields_appear(self) -> None:
        from cairn.observability.logging import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="cairn.test", level=logging.INFO, pathname="x", lineno=1,
            msg="event", args=(), exc_info=None,
        )
        record.user_id = "u_42"
        record.trace_id = "abc"
        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["user_id"], "u_42")

    def test_exception_info_serialized(self) -> None:
        from cairn.observability.logging import JsonFormatter
        formatter = JsonFormatter()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys as _sys
            record = logging.LogRecord(
                name="cairn.test", level=logging.ERROR, pathname="x", lineno=1,
                msg="failed", args=(), exc_info=_sys.exc_info(),
            )
            record.trace_id = "abc"
            payload = json.loads(formatter.format(record))
        self.assertIn("exc", payload)
        self.assertIn("RuntimeError", payload["exc"])
        self.assertIn("boom", payload["exc"])


class MetricsTests(unittest.TestCase):
    def test_render_includes_known_metrics(self) -> None:
        from cairn.observability.metrics import (
            DISPATCHER_TICKS,
            HTTP_REQUESTS,
            render_metrics,
        )
        HTTP_REQUESTS.labels(method="GET", path="/x", status="200").inc()
        DISPATCHER_TICKS.inc()
        body, content_type = render_metrics()
        self.assertIn(b"cairn_http_requests_total", body)
        self.assertIn(b"cairn_dispatcher_ticks_total", body)
        self.assertTrue(content_type.startswith("text/plain"))


class ObservabilityDbTests(unittest.TestCase):
    def setUp(self) -> None:
        from cairn.server import db

        reset_postgres_db()
        self.db = db

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def test_batch_append_persists_events(self) -> None:
        from cairn.server.observability.events_writer import append_events
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        with self.db.session_scope() as conn:
            create_execution(
                conn,
                "proj_001",
                CreateExecutionRequest(id="exec_1", intent_id=None, task_type="reason", worker="w"),
            )
            events, dropped = append_events(
                conn,
                "proj_001",
                "exec_1",
                [
                    CreateEventRequest(phase="p", event_kind="stdout", stream="stdout", content="one"),
                    CreateEventRequest(phase="p", event_kind="stderr", stream="stderr", content="two"),
                ],
                ObservabilitySettings(),
            )
        self.assertEqual(dropped, 0)
        self.assertEqual(len(events), 2)
        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            row = sql.fetchone(conn, "SELECT COUNT(*) AS count FROM llm_execution_events")
            assert row is not None
            count = row["count"]
        self.assertEqual(count, 2)

    def test_status_reports_postgres(self) -> None:
        status = self.db.postgres_status()
        self.assertEqual(status["database"], "postgresql")
        self.assertTrue(status["ok"])


class RequestIdMiddlewareTests(unittest.TestCase):
    def _build(self):
        yaml_cfg = TempYamlConfig()
        yaml_cfg.__enter__()
        reset_postgres_db()
        from fastapi.testclient import TestClient

        from cairn.server.app import app
        return TestClient(app), yaml_cfg

    def test_request_id_round_trip(self) -> None:
        client, yaml_cfg = self._build()
        try:
            r = client.get("/metrics")  # public, easy to assert against
            self.assertIn("x-request-id", r.headers)
            # Set a custom id; the response echoes it back.
            r2 = client.get("/metrics", headers={"X-Request-Id": "trace-from-test"})
            self.assertEqual(r2.headers["x-request-id"], "trace-from-test")
        finally:
            yaml_cfg.__exit__(None, None, None)
