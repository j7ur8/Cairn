from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import TempYamlConfig, reset_postgres_db


class RetentionLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        from cairn.server import db
        from cairn.server.repositories import sql

        reset_postgres_db()
        self.db = db
        # Seed an old and a new execution.
        with db.session_scope() as conn:
            old_started = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
            new_started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for started_at, exec_id in ((old_started, "old-1"), (new_started, "new-1")):
                sql.execute(
                    conn,
                    """
                    INSERT INTO llm_executions (
                        id, project_id, worker, task_type, process_state, started_at
                    ) VALUES (
                        :id, :project_id, :worker, :task_type, :process_state, :started_at
                    )
                    """,
                    {
                        "id": exec_id,
                        "project_id": "p1",
                        "worker": "codex",
                        "task_type": "explore",
                        "process_state": "completed",
                        "started_at": started_at,
                    },
                )
                sql.execute(
                    conn,
                    """
                    INSERT INTO llm_execution_events (
                        execution_id, project_id, task_type, worker, phase,
                        event_kind, stream, content, created_at
                    ) VALUES (
                        :execution_id, :project_id, :task_type, :worker, :phase,
                        :event_kind, :stream, :content, :created_at
                    )
                    """,
                    {
                        "execution_id": exec_id,
                        "project_id": "p1",
                        "task_type": "explore",
                        "worker": "codex",
                        "phase": "run",
                        "event_kind": "prompt",
                        "stream": "stdout",
                        "content": "{}",
                        "created_at": started_at,
                    },
                )

    def tearDown(self) -> None:
        from cairn.server import db
        db.reset_for_tests()

    def test_run_sweep_deletes_old_keeps_new(self) -> None:
        from cairn.server.observability.retention import run_sweep

        deleted = run_sweep(hours=24)
        self.assertEqual(deleted, 1)
        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            rows = sql.fetchall(conn, "SELECT id FROM llm_executions")
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"new-1"})

    def test_retention_loop_runs_and_stops(self) -> None:
        yaml_cfg = TempYamlConfig()
        yaml_cfg.dispatch["observability"] = {"retention_days": 1}
        yaml_cfg.__enter__()
        try:
            self._run_loop_scenario()
        finally:
            yaml_cfg.__exit__(None, None, None)

    def _run_loop_scenario(self) -> None:
        from cairn.server.observability.retention import retention_loop

        async def scenario() -> None:
            stop = asyncio.Event()
            task = asyncio.create_task(retention_loop(stop, interval_seconds=60))
            # Give the loop a moment to do its first sweep (it does so
            # immediately on entry, before the first sleep).
            await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(task, timeout=2.0)

        asyncio.run(scenario())
        # After the loop ran once, the old execution should be gone.
        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            rows = sql.fetchall(conn, "SELECT id FROM llm_executions")
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"new-1"})

    def test_retention_hours_from_dispatch_yaml(self) -> None:
        from cairn.server.observability import retention

        yaml_cfg = TempYamlConfig()
        yaml_cfg.dispatch["observability"] = {"retention_days": 1}
        yaml_cfg.__enter__()
        try:
            self.assertEqual(retention.retention_hours(), 24)
            yaml_cfg.dispatch_path.write_text(
                "observability:\n  retention_days: not-an-int\n",
                encoding="utf-8",
            )
            self.assertEqual(retention.retention_hours(), retention.DEFAULT_RETENTION_HOURS)
            yaml_cfg.dispatch_path.write_text(
                "observability:\n  retention_days: 0\n",
                encoding="utf-8",
            )
            self.assertEqual(retention.retention_hours(), retention.DEFAULT_RETENTION_HOURS)
        finally:
            yaml_cfg.__exit__(None, None, None)


if __name__ == "__main__":
    unittest.main()
