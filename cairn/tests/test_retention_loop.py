from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class RetentionLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        from cairn.server.observability import db as obs_db
        obs_db._db_path = None
        obs_db.configure(Path(self.tmp.name))
        self.obs_db = obs_db
        # Seed an old and a new execution.
        with obs_db.get_conn() as conn:
            old_started = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
            new_started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for started_at, exec_id in ((old_started, "old-1"), (new_started, "new-1")):
                conn.execute(
                    "INSERT INTO llm_executions (id, project_id, worker, task_type, process_state, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (exec_id, "p1", "codex", "explore", "completed", started_at),
                )
                conn.execute(
                    "INSERT INTO llm_execution_events (execution_id, project_id, task_type, worker, phase, event_kind, stream, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (exec_id, "p1", "explore", "codex", "run", "prompt", "stdout", "{}", started_at),
                )

    def tearDown(self) -> None:
        self.obs_db._db_path = None
        os.unlink(self.tmp.name)

    def test_run_sweep_deletes_old_keeps_new(self) -> None:
        from cairn.server.observability.retention import run_sweep

        deleted = run_sweep(hours=24)
        self.assertEqual(deleted, 1)
        with self.obs_db.get_conn() as conn:
            rows = conn.execute("SELECT id FROM llm_executions").fetchall()
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"new-1"})

    def test_retention_loop_runs_and_stops(self) -> None:
        from cairn.server.observability.retention import retention_loop

        original = os.environ.get("OBSERVABILITY_RETENTION_HOURS")
        os.environ["OBSERVABILITY_RETENTION_HOURS"] = "1"
        try:
            self._run_loop_scenario()
        finally:
            if original is None:
                os.environ.pop("OBSERVABILITY_RETENTION_HOURS", None)
            else:
                os.environ["OBSERVABILITY_RETENTION_HOURS"] = original

    def _run_loop_scenario(self) -> None:
        from cairn.server.observability.retention import retention_loop

        async def scenario() -> None:
            stop = asyncio.Event()
            task = asyncio.create_task(retention_loop(stop))
            # Give the loop a moment to do its first sweep (it does so
            # immediately on entry, before the first sleep).
            await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(task, timeout=2.0)

        asyncio.run(scenario())
        # After the loop ran once, the old execution should be gone.
        with self.obs_db.get_conn() as conn:
            rows = conn.execute("SELECT id FROM llm_executions").fetchall()
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"new-1"})

    def test_retention_hours_from_env(self) -> None:
        from cairn.server.observability import retention

        original = os.environ.get("OBSERVABILITY_RETENTION_HOURS")
        try:
            os.environ["OBSERVABILITY_RETENTION_HOURS"] = "1"
            self.assertEqual(retention.retention_hours(), 1)
            os.environ["OBSERVABILITY_RETENTION_HOURS"] = "not-an-int"
            self.assertEqual(retention.retention_hours(), retention.DEFAULT_RETENTION_HOURS)
            os.environ["OBSERVABILITY_RETENTION_HOURS"] = "0"
            self.assertEqual(retention.retention_hours(), retention.DEFAULT_RETENTION_HOURS)
        finally:
            if original is None:
                os.environ.pop("OBSERVABILITY_RETENTION_HOURS", None)
            else:
                os.environ["OBSERVABILITY_RETENTION_HOURS"] = original


if __name__ == "__main__":
    unittest.main()
