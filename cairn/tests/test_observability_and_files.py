from __future__ import annotations

import os

os.environ.setdefault('CAIRN_JWT_SECRET', 'test-jwt-secret-do-not-use-in-prod-32bytes')
os.environ.setdefault('CAIRN_SECRETS_KEY', 'test-jwt-secret-do-not-use-in-prod-32bytes')

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import TempYamlConfig, reset_postgres_db


class ObservabilityRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        from cairn.server import db

        reset_postgres_db()
        self.db = db
        self.conn_cm = db.session_scope()
        self.conn = self.conn_cm.__enter__()

    def tearDown(self) -> None:
        self.conn_cm.__exit__(None, None, None)
        self.db.reset_for_tests()

    def test_recreating_execution_preserves_existing_event_counters(self) -> None:
        from cairn.server.observability.events_query import list_project_events
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution, finish_execution, list_executions
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            FinishExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_obs"
        body = CreateExecutionRequest(
            id="exec_1",
            intent_id=None,
            task_type="reason",
            worker="worker-a",
        )
        create_execution(self.conn, project_id, body)
        event, dropped = append_event(
            self.conn,
            project_id,
            "exec_1",
            CreateEventRequest(
                phase="reason_execute",
                event_kind="usage",
                stream="system",
                content='{"summary":"token usage"}',
            ),
            ObservabilitySettings(),
        )
        self.assertFalse(dropped)
        self.assertIsNotNone(event)

        create_execution(self.conn, project_id, body)

        from cairn.server.repositories import sql

        sql.execute(
            self.conn,
            """
            UPDATE llm_executions
            SET event_count = 0, bytes_written = 0, last_event_at = NULL
            WHERE id = :id
            """,
            {"id": "exec_1"},
        )

        executions = list_executions(self.conn, project_id, 10)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].event_count, 1)
        self.assertGreater(executions[0].bytes_written, 0)
        self.assertIsNotNone(executions[0].last_event_at)
        events = list_project_events(self.conn, project_id, 0, 10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_kind, "usage")

        finish_execution(
            self.conn,
            project_id,
            "exec_1",
            FinishExecutionRequest(process_state="cancelled", error_kind="cancelled"),
        )
        finish_execution(
            self.conn,
            project_id,
            "exec_1",
            FinishExecutionRequest(process_state="cancelled", error_kind="cancelled"),
        )

        events = list_project_events(self.conn, project_id, 0, 10)
        process_end_events = [event for event in events if event.event_kind == "process_end"]
        self.assertEqual(len(process_end_events), 1)
        self.assertIn("process_state=cancelled", process_end_events[0].content)

    def test_capability_manifest_event_kind_is_accepted(self) -> None:
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_caps"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(
                id="exec_caps",
                intent_id="i001",
                task_type="bootstrap",
                worker="worker-a",
            ),
        )
        event, dropped = append_event(
            self.conn,
            project_id,
            "exec_caps",
            CreateEventRequest(
                phase="bootstrap_start",
                event_kind="capability_manifest",
                stream="system",
                content='{"summary":"Project capabilities before bootstrap"}',
            ),
            ObservabilitySettings(),
        )
        self.assertFalse(dropped)
        self.assertIsNotNone(event)
        self.assertEqual(event.event_kind, "capability_manifest")

    def test_batch_append_updates_execution_stats_once(self) -> None:
        from cairn.server.observability.events_writer import append_events
        from cairn.server.observability.executions import create_execution, list_executions
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )
        from cairn.server.repositories import sql

        project_id = "proj_batch"
        execution_id = "exec_batch"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )

        events, dropped = append_events(
            self.conn,
            project_id,
            execution_id,
            [
                CreateEventRequest(phase="bootstrap", event_kind="stdout", stream="stdout", content="one"),
                CreateEventRequest(phase="bootstrap", event_kind="stderr", stream="stderr", content="two"),
                CreateEventRequest(phase="bootstrap", event_kind="agent_message", stream="result", content="three"),
            ],
            ObservabilitySettings(),
        )

        self.assertEqual(dropped, 0)
        self.assertEqual([event.content for event in events if event is not None], ["one", "two", "three"])
        row = sql.fetchone(self.conn, "SELECT COUNT(*) AS count FROM llm_execution_events WHERE execution_id = :id", {"id": execution_id})
        self.assertEqual(row["count"], 3)
        execution = list_executions(self.conn, project_id, 10)[0]
        self.assertEqual(execution.event_count, 3)
        self.assertEqual(execution.bytes_written, len(b"onetwothree"))
        self.assertIsNotNone(execution.last_event_at)

    def test_incremental_events_are_filtered_by_execution_and_after(self) -> None:
        from cairn.server.observability.events_query import list_incremental_events
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_incremental"
        for execution_id in ("exec_a", "exec_b"):
            create_execution(
                self.conn,
                project_id,
                CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
            )
        event_a1, _ = append_event(
            self.conn,
            project_id,
            "exec_a",
            CreateEventRequest(phase="bootstrap", event_kind="stdout", stream="stdout", content="a1"),
            ObservabilitySettings(),
        )
        append_event(
            self.conn,
            project_id,
            "exec_b",
            CreateEventRequest(phase="bootstrap", event_kind="stdout", stream="stdout", content="b1"),
            ObservabilitySettings(),
        )
        append_event(
            self.conn,
            project_id,
            "exec_a",
            CreateEventRequest(phase="bootstrap", event_kind="stdout", stream="stdout", content="a2"),
            ObservabilitySettings(),
        )
        self.assertIsNotNone(event_a1)

        events, last_sequence = list_incremental_events(
            self.conn,
            project_id,
            execution_id="exec_a",
            after=event_a1.sequence,
            limit=10,
        )

        self.assertEqual([event.content for event in events], ["a2"])
        self.assertEqual(last_sequence, events[-1].sequence)

    def test_incremental_event_kinds_filter_does_not_spend_limit_on_usage(self) -> None:
        from cairn.server.observability.events_query import list_incremental_events
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_incremental_kinds"
        execution_id = "exec_incremental_kinds"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        for index in range(5):
            append_event(
                self.conn,
                project_id,
                execution_id,
                CreateEventRequest(phase="bootstrap", event_kind="usage", stream="system", content=f"usage-{index}"),
                ObservabilitySettings(),
            )
        append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(phase="bootstrap", event_kind="command_start", stream="system", content="start"),
            ObservabilitySettings(),
        )
        append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(phase="bootstrap", event_kind="process_end", stream="system", content="done"),
            ObservabilitySettings(),
        )

        events, last_sequence = list_incremental_events(
            self.conn,
            project_id,
            execution_id=execution_id,
            limit=2,
            event_kinds=["command_start", "process_end"],
        )

        self.assertEqual([event.content for event in events], ["start", "done"])
        self.assertEqual(last_sequence, events[-1].sequence)

    def test_incremental_event_kinds_filter_advances_cursor_when_no_events_match(self) -> None:
        from cairn.server.observability.events_query import list_incremental_events
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_incremental_cursor"
        execution_id = "exec_incremental_cursor"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        last_event = None
        for index in range(3):
            last_event, _ = append_event(
                self.conn,
                project_id,
                execution_id,
                CreateEventRequest(phase="bootstrap", event_kind="usage", stream="system", content=f"usage-{index}"),
                ObservabilitySettings(),
            )
        self.assertIsNotNone(last_event)

        events, last_sequence = list_incremental_events(
            self.conn,
            project_id,
            execution_id=execution_id,
            limit=2,
            event_kinds=["command_start"],
        )

        self.assertEqual(events, [])
        self.assertEqual(last_sequence, last_event.sequence)

    def test_incremental_empty_event_kinds_filter_returns_no_events_and_advances_cursor(self) -> None:
        from cairn.server.observability.events_query import list_incremental_events
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_incremental_empty_kinds"
        execution_id = "exec_incremental_empty_kinds"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        event, _ = append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(phase="bootstrap", event_kind="agent_message", stream="result", content="visible"),
            ObservabilitySettings(),
        )
        self.assertIsNotNone(event)

        events, last_sequence = list_incremental_events(
            self.conn,
            project_id,
            execution_id=execution_id,
            limit=2,
            event_kinds=[""],
        )

        self.assertEqual(events, [])
        self.assertEqual(last_sequence, event.sequence)

    def test_event_cards_page_by_merged_cards_without_duplicates(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        from cairn.server.observability.event_card_service import list_event_cards

        def event(sequence: int, kind: str, content: str, *, stream: str = "system"):
            return SimpleNamespace(
                sequence=sequence,
                execution_id="exec_cards",
                project_id="proj_cards",
                intent_id="i001",
                task_type="reason",
                worker="worker-a",
                phase="reason",
                event_kind=kind,
                stream=stream,
                content=content,
                truncated=0,
                redacted=0,
                created_at=f"2026-06-19T00:00:{sequence:02d}Z",
                model_dump=lambda: {
                    "sequence": sequence,
                    "execution_id": "exec_cards",
                    "project_id": "proj_cards",
                    "intent_id": "i001",
                    "task_type": "reason",
                    "worker": "worker-a",
                    "phase": "reason",
                    "event_kind": kind,
                    "stream": stream,
                    "content": content,
                    "truncated": 0,
                    "redacted": 0,
                    "created_at": f"2026-06-19T00:00:{sequence:02d}Z",
                },
            )

        rows = [
            event(1, "tool_call", '{"call_id":"call-1","tool":"exec_command","arguments":{"cmd":"echo 1"}}'),
            event(2, "command_start", '{"call_id":"call-1","command":"echo 1","workdir":"/tmp"}'),
            event(3, "command_end", '{"call_id":"call-1","status":"completed","stdout":"1","command":"echo 1"}'),
            event(4, "agent_message", "plain-1", stream="result"),
            event(5, "tool_call", '{"call_id":"call-2","tool":"exec_command","arguments":{"cmd":"echo 2"}}'),
            event(6, "command_start", '{"call_id":"call-2","command":"echo 2","workdir":"/tmp"}'),
            event(7, "command_end", '{"call_id":"call-2","status":"completed","stdout":"2","command":"echo 2"}'),
            event(8, "agent_message", "plain-2", stream="result"),
            event(9, "agent_message", "plain-3", stream="result"),
        ]

        with patch("cairn.server.observability.event_card_service._list_filtered_events", return_value=(rows, 9)):
            first_page = list_event_cards(object(), "proj_cards", execution_id="exec_cards", page_size=2)
            second_page = list_event_cards(
                object(),
                "proj_cards",
                execution_id="exec_cards",
                page_size=2,
                page_token=first_page.next_page_token,
            )
            third_page = list_event_cards(
                object(),
                "proj_cards",
                execution_id="exec_cards",
                page_size=2,
                page_token=second_page.next_page_token,
            )

        self.assertEqual(len(first_page.cards), 2)
        self.assertTrue(first_page.has_next)
        self.assertEqual([card.sequence for card in first_page.cards], [3, 4])
        self.assertTrue(first_page.cards[0].merged_call)
        self.assertEqual(first_page.page_range_label, "#3-#4")
        self.assertEqual([card.sequence for card in second_page.cards], [7, 8])
        self.assertTrue(second_page.has_next)
        self.assertTrue(second_page.cards[0].merged_call)
        self.assertEqual([card.sequence for card in third_page.cards], [9])
        self.assertFalse(third_page.has_next)

    def test_event_cards_filter_keeps_page_size_stable(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        from cairn.server.observability.event_card_service import list_event_cards

        def event(sequence: int, content: str):
            return SimpleNamespace(
                sequence=sequence,
                execution_id="exec_cards_filter",
                project_id="proj_cards_filter",
                intent_id="i001",
                task_type="reason",
                worker="worker-a",
                phase="reason",
                event_kind="agent_message",
                stream="result",
                content=content,
                truncated=0,
                redacted=0,
                created_at=f"2026-06-19T00:00:{sequence:02d}Z",
                model_dump=lambda: {
                    "sequence": sequence,
                    "execution_id": "exec_cards_filter",
                    "project_id": "proj_cards_filter",
                    "intent_id": "i001",
                    "task_type": "reason",
                    "worker": "worker-a",
                    "phase": "reason",
                    "event_kind": "agent_message",
                    "stream": "result",
                    "content": content,
                    "truncated": 0,
                    "redacted": 0,
                    "created_at": f"2026-06-19T00:00:{sequence:02d}Z",
                },
            )

        rows = [event(2, "visible-0"), event(4, "visible-1"), event(6, "visible-2")]
        with patch("cairn.server.observability.event_card_service._list_filtered_events", return_value=(rows, 6)):
            page = list_event_cards(
                object(),
                "proj_cards_filter",
                execution_id="exec_cards_filter",
                page_size=2,
                event_kinds=["agent_message"],
            )
            next_page = list_event_cards(
                object(),
                "proj_cards_filter",
                execution_id="exec_cards_filter",
                page_size=2,
                event_kinds=["agent_message"],
                page_token=page.next_page_token,
            )

        self.assertEqual([card.content for card in page.cards], ["visible-0", "visible-1"])
        self.assertTrue(page.has_next)
        self.assertEqual([card.content for card in next_page.cards], ["visible-2"])
        self.assertFalse(next_page.has_next)

    def test_tail_project_events_returns_latest_events_in_ascending_order(self) -> None:
        from cairn.server.observability.events_query import list_project_events
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_tail"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id="exec_tail", intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        for index in range(5):
            append_event(
                self.conn,
                project_id,
                "exec_tail",
                CreateEventRequest(
                    phase="bootstrap",
                    event_kind="agent_message",
                    stream="result",
                    content=f"event-{index}",
                ),
                ObservabilitySettings(),
            )

        events = list_project_events(self.conn, project_id, after=0, limit=3, tail=True)

        self.assertEqual([event.content for event in events], ["event-2", "event-3", "event-4"])
        self.assertEqual([event.sequence for event in events], sorted(event.sequence for event in events))

    def test_tail_execution_events_is_scoped_to_execution(self) -> None:
        from cairn.server.observability.events_query import list_execution_events
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )

        project_id = "proj_tail_exec"
        for execution_id in ("exec_a", "exec_b"):
            create_execution(
                self.conn,
                project_id,
                CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
            )
        for index in range(4):
            append_event(
                self.conn,
                project_id,
                "exec_a",
                CreateEventRequest(phase="bootstrap", event_kind="agent_message", stream="result", content=f"a-{index}"),
                ObservabilitySettings(),
            )
            append_event(
                self.conn,
                project_id,
                "exec_b",
                CreateEventRequest(phase="bootstrap", event_kind="agent_message", stream="result", content=f"b-{index}"),
                ObservabilitySettings(),
            )

        events = list_execution_events(self.conn, project_id, "exec_a", after=0, limit=2, tail=True)

        self.assertEqual([event.content for event in events], ["a-2", "a-3"])
        self.assertTrue(all(event.execution_id == "exec_a" for event in events))

    def test_event_view_allowlist_keeps_primary_events_when_usage_is_noisy(self) -> None:
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )
        from cairn.server.observability.view_service import list_event_view

        project_id = "proj_view"
        execution_id = "exec_view"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        for index in range(25):
            append_event(
                self.conn,
                project_id,
                execution_id,
                CreateEventRequest(
                    phase="bootstrap",
                    event_kind="usage",
                    stream="system",
                    content=f'{{"subtype":"thinking_tokens","estimated_tokens":{index},"estimated_tokens_delta":1}}',
                ),
                ObservabilitySettings(),
            )
        append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(phase="bootstrap", event_kind="command_start", stream="system", content="curl target"),
            ObservabilitySettings(),
        )
        append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(phase="bootstrap", event_kind="process_end", stream="system", content="done"),
            ObservabilitySettings(),
        )

        view = list_event_view(
            self.conn,
            project_id,
            execution_id=execution_id,
            limit=10,
            event_kinds=["command_start", "process_end"],
        )

        self.assertEqual([event.event_kind for event in view.primary_events], ["process_end", "command_start"])
        self.assertFalse(hasattr(view, "activity"))
        self.assertEqual(view.stats.hidden_by_kind["usage"], 25)
        self.assertEqual(view.last_sequence, view.primary_events[0].sequence)

    def test_event_view_without_event_kinds_returns_all_event_kinds(self) -> None:
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )
        from cairn.server.observability.view_service import list_event_view

        project_id = "proj_view_low"
        execution_id = "exec_view_low"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        for kind in ("usage", "prompt", "capability_manifest", "agent_message"):
            append_event(
                self.conn,
                project_id,
                execution_id,
                CreateEventRequest(phase="bootstrap", event_kind=kind, stream="system" if kind != "agent_message" else "result", content=kind),
                ObservabilitySettings(),
            )

        view = list_event_view(self.conn, project_id, execution_id=execution_id, limit=10)

        self.assertEqual(
            [event.event_kind for event in view.primary_events],
            ["agent_message", "capability_manifest", "prompt", "usage"],
        )
        self.assertEqual(view.stats.hidden_by_kind, {})

    def test_event_view_event_kinds_allowlist_hides_unselected_kinds(self) -> None:
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )
        from cairn.server.observability.view_service import list_event_view

        project_id = "proj_view_default"
        execution_id = "exec_view_default"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        for kind in ("usage", "prompt", "capability_manifest", "agent_message"):
            append_event(
                self.conn,
                project_id,
                execution_id,
                CreateEventRequest(phase="bootstrap", event_kind=kind, stream="system" if kind != "agent_message" else "result", content=kind),
                ObservabilitySettings(),
            )

        view = list_event_view(
            self.conn,
            project_id,
            execution_id=execution_id,
            limit=10,
            event_kinds=["prompt", "capability_manifest", "agent_message"],
        )

        self.assertEqual(
            [event.event_kind for event in view.primary_events],
            ["agent_message", "capability_manifest", "prompt"],
        )
        self.assertEqual(view.stats.hidden_by_kind, {"usage": 1})

    def test_event_view_empty_event_kinds_filter_returns_no_primary_events(self) -> None:
        from cairn.server.observability.events_writer import append_event
        from cairn.server.observability.executions import create_execution
        from cairn.server.observability.models import (
            CreateEventRequest,
            CreateExecutionRequest,
            ObservabilitySettings,
        )
        from cairn.server.observability.view_service import list_event_view

        project_id = "proj_view_empty_kinds"
        execution_id = "exec_view_empty_kinds"
        create_execution(
            self.conn,
            project_id,
            CreateExecutionRequest(id=execution_id, intent_id="i001", task_type="bootstrap", worker="worker-a"),
        )
        event, _ = append_event(
            self.conn,
            project_id,
            execution_id,
            CreateEventRequest(phase="bootstrap", event_kind="agent_message", stream="result", content="visible"),
            ObservabilitySettings(),
        )
        self.assertIsNotNone(event)

        view = list_event_view(self.conn, project_id, execution_id=execution_id, limit=10, event_kinds=[""])

        self.assertEqual(view.primary_events, [])
        self.assertEqual(view.stats.hidden_by_kind, {"agent_message": 1})
        self.assertEqual(view.last_sequence, event.sequence)


class ProjectFilesRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmpdir.name) / "project-files"
        self.attachments_root = Path(self.tmpdir.name) / "attachments"
        self.yaml = TempYamlConfig()
        self.yaml.dispatch["server"]["paths"]["project_files_root"] = str(self.project_root)
        self.yaml.dispatch["server"]["paths"]["attachments_root"] = str(self.attachments_root)
        self.yaml.__enter__()

        from cairn.server import db

        reset_postgres_db()
        self.db = db
        with db.session_scope() as conn:
            from cairn.server.repositories import sql

            sql.execute(
                conn,
                """
                INSERT INTO projects (id, title, status, created_at, graph_revision, timeline_revision)
                VALUES (:id, :title, 'active', :created_at, 1, 1)
                """,
                {
                    "id": "proj_files",
                    "title": "Files",
                    "created_at": "2026-06-05T00:00:00Z",
                },
            )

        from cairn.server.routers import files

        self.files_router = files

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        self.yaml.__exit__(None, None, None)
        self.tmpdir.cleanup()

    def test_project_files_lists_runtime_outputs_and_attachments(self) -> None:
        (self.project_root / "proj_files" / "reports").mkdir(parents=True)
        (self.project_root / "proj_files" / "exploit").mkdir(parents=True)
        (self.project_root / "proj_files" / "reports" / "writeup.md").write_text("report", encoding="utf-8")
        (self.project_root / "proj_files" / "exploit" / "solve.py").write_text("print(1)\n", encoding="utf-8")
        (self.project_root / "proj_files" / "reports" / "ctf-web-js-analysis").mkdir(parents=True)
        (self.project_root / "proj_files" / "reports" / "ctf-web-js-analysis" / "information_api.json").write_text("{}", encoding="utf-8")
        (self.project_root / "proj_files" / "reports" / "ctf-web-js-analysis" / "information_leak.json").write_text("{}", encoding="utf-8")
        (self.project_root / "proj_files" / "reports" / "ctf-web-js-analysis" / "js_inventory.json").write_text("{}", encoding="utf-8")
        (self.attachments_root / "proj_files").mkdir(parents=True)
        (self.attachments_root / "proj_files" / "input.txt").write_text("attachment", encoding="utf-8")

        response = self.files_router.list_project_files("proj_files")
        by_path = {item.path: item for item in response.files}

        self.assertEqual(by_path["reports/writeup.md"].category, "reports")
        self.assertEqual(by_path["reports/ctf-web-js-analysis/information_api.json"].category, "reports")
        self.assertEqual(by_path["reports/ctf-web-js-analysis/information_leak.json"].category, "reports")
        self.assertEqual(by_path["reports/ctf-web-js-analysis/js_inventory.json"].category, "reports")
        self.assertEqual(by_path["exploit/solve.py"].category, "exploit")
        self.assertEqual(by_path["input.txt"].source, "attachment")
        self.assertEqual(by_path["input.txt"].category, "attachments")

    def test_project_file_download_rejects_path_traversal(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self.files_router.download_project_file(
                "proj_files",
                source="project",
                path="../secret.txt",
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_project_file_download_resolves_runtime_file(self) -> None:
        target = self.project_root / "proj_files" / "reports" / "writeup.md"
        target.parent.mkdir(parents=True)
        target.write_text("report", encoding="utf-8")

        response = self.files_router.download_project_file(
            "proj_files",
            source="project",
            path="reports/writeup.md",
        )
        self.assertEqual(Path(response.path).name, "writeup.md")


if __name__ == "__main__":
    unittest.main()
