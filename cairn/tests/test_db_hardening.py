from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class DbHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db
        db._db_path = None
        db.close_thread_conn()
        db.configure(Path(self.tmp.name))
        self.db = db

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db._db_path = None
        os.unlink(self.tmp.name)

    def _project_ai_profile_selections(self):
        from cairn.server.models import AiProfileCreate, AiProfileSelection, TaskAiProfileSelections
        from cairn.server.routers.ai_profiles import create_ai_profile

        profile = create_ai_profile(
            AiProfileCreate(
                name="test-profile",
                worker_type="codex",
                model="test-model",
                api_key_env="OPENAI_API_KEY",
            )
        )
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="test-model",
            primary_reasoning_type="medium",
        )
        return TaskAiProfileSelections(
            bootstrap=selection,
            explore=selection,
            reason=selection,
        )

    def test_get_conn_reuses_thread_connection(self) -> None:
        ids = []
        with self.db.get_conn() as conn:
            ids.append(id(conn))
        with self.db.get_conn() as conn:
            ids.append(id(conn))
        self.assertEqual(ids[0], ids[1])

    def test_connections_are_thread_local(self) -> None:
        results: list[int] = []

        def worker() -> None:
            with self.db.get_conn() as conn:
                results.append(id(conn))
            self.db.close_thread_conn()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(len(results), 2)
        self.assertNotEqual(results[0], results[1])

    def test_with_immediate_tx_commits(self) -> None:
        with self.db.with_immediate_tx() as conn:
            conn.execute("INSERT INTO users (id, email, hashed_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                         ("u1", "a@example.com", "x", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT email FROM users WHERE id = 'u1'").fetchone()
        self.assertEqual(row["email"], "a@example.com")

    def test_migration_error_table_exists(self) -> None:
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='migration_errors'").fetchone()
        self.assertIsNotNone(row)

    def test_state_uniqueness_indexes_exist(self) -> None:
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                  AND name IN ('idx_intents_project_goal_once', 'idx_intents_project_fact_once')
                """
            ).fetchall()
        self.assertEqual(
            {row["name"] for row in rows},
            {"idx_intents_project_goal_once", "idx_intents_project_fact_once"},
        )

    def test_online_backup_can_be_restored(self) -> None:
        with self.db.with_immediate_tx() as conn:
            conn.execute(
                "INSERT INTO users (id, email, hashed_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("u_backup", "backup@example.com", "x", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
        backup_path = Path(self.tmp.name).with_name("backup.sqlite")
        created = self.db.backup_to(backup_path)
        self.assertEqual(created, backup_path)
        conn = sqlite3.connect(str(backup_path))
        try:
            row = conn.execute("SELECT email FROM users WHERE id = 'u_backup'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "backup@example.com")

    def test_concurrent_conclude_produces_one_fact(self) -> None:
        from cairn.server.models import ConcludeRequest, CreateIntentRequest, CreateProjectRequest
        from cairn.server.routers.intents import conclude, create_intent
        from cairn.server.routers.projects import create_project

        project = create_project(
            CreateProjectRequest(
                title="p",
                origin="o",
                goal="g",
                ai_profile_selections=self._project_ai_profile_selections(),
            )
        )
        intent = create_intent(
            project.project.id,
            CreateIntentRequest(
                **{"from": ["origin"]},
                description="try",
                creator="worker",
                worker="worker",
            ),
        )

        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                response = conclude(
                    project.project.id,
                    intent.id,
                    ConcludeRequest(worker="worker", description="fact"),
                )
                results.append(response.fact.id)
            except Exception as exc:  # noqa: BLE001 - asserting race outcome
                errors.append(exc)
            finally:
                self.db.close_thread_conn()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        with self.db.get_conn() as conn:
            fact_count = conn.execute(
                "SELECT COUNT(*) AS count FROM facts WHERE project_id = ? AND id NOT IN ('origin', 'goal')",
                (project.project.id,),
            ).fetchone()["count"]
        self.assertEqual(fact_count, 1)

    def test_concurrent_complete_produces_one_goal_intent(self) -> None:
        from cairn.server.models import CompleteRequest, CreateProjectRequest
        from cairn.server.routers.projects import complete_project, create_project

        project = create_project(
            CreateProjectRequest(
                title="p",
                origin="o",
                goal="g",
                ai_profile_selections=self._project_ai_profile_selections(),
            )
        )
        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                response = complete_project(
                    project.project.id,
                    CompleteRequest(**{"from": ["origin"]}, description="done", worker="worker"),
                )
                results.append(response.id)
            except Exception as exc:  # noqa: BLE001 - asserting race outcome
                errors.append(exc)
            finally:
                self.db.close_thread_conn()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        with self.db.get_conn() as conn:
            goal_count = conn.execute(
                "SELECT COUNT(*) AS count FROM intents WHERE project_id = ? AND to_fact_id = 'goal'",
                (project.project.id,),
            ).fetchone()["count"]
        self.assertEqual(goal_count, 1)

    def test_apply_migrations_records_errors(self) -> None:
        """A migration whose SQL fails should land a row in
        ``migration_errors`` so operators see the failure at the next
        ``/health`` probe rather than silently losing a schema change.
        """
        from cairn.server import db as server_db
        # Monkeypatch MIGRATIONS to include a guaranteed-failing entry
        # at the end so it runs after the real ones and the
        # ``schema_migrations`` row is missing.
        sentinel = (
            "20999999_999_bogus",
            "CREATE TABLE this is not valid SQL;",
        )
        original = list(server_db.MIGRATIONS)
        server_db.MIGRATIONS = original + [sentinel]
        try:
            with self.db.get_conn() as conn:
                with self.assertRaises(Exception):
                    server_db._apply_migrations(conn)
        finally:
            server_db.MIGRATIONS = original
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT version, error FROM migration_errors WHERE version = ?",
                (sentinel[0],),
            ).fetchone()
        self.assertIsNotNone(row, "expected migration_errors row for failed migration")
        self.assertEqual(row["version"], sentinel[0])
        self.assertIn("syntax", row["error"].lower())

    def test_open_conn_falls_back_to_delete_when_wal_setup_fails(self) -> None:
        from cairn.server import db as server_db

        original_connect = server_db.sqlite3.connect

        class ProxyConnection:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, *args):
                if sql == "PRAGMA journal_mode=WAL":
                    raise sqlite3.DatabaseError("disk I/O error")
                return self._inner.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        def fake_connect(*args, **kwargs):
            return ProxyConnection(original_connect(*args, **kwargs))

        server_db.close_thread_conn()
        server_db.sqlite3.connect = fake_connect  # type: ignore[assignment]
        try:
            with self.db.get_conn() as conn:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "delete")
        finally:
            server_db.sqlite3.connect = original_connect  # type: ignore[assignment]
            server_db.close_thread_conn()

    def test_sqlite_status_includes_quick_check_and_file_state(self) -> None:
        status = self.db.sqlite_status()
        self.assertEqual(status["quick_check"], ["ok"])
        self.assertNotIn("wal_checkpoint", status)
        self.assertIn("wal_size_bytes", status)
        self.assertIn("shm_size_bytes", status)
        self.assertIn("mtime", status)

    def test_checkpoint_truncate_reports_before_and_after(self) -> None:
        result = self.db.checkpoint_truncate()
        self.assertEqual(result["path"], self.tmp.name)
        self.assertIn("before", result)
        self.assertIn("checkpoint", result)
        self.assertIn("after", result)
        self.assertEqual(self.db.quick_check(), ["ok"])

    def test_diagnostic_error_includes_sqlite_file_state(self) -> None:
        detail = self.db.diagnostic_error(sqlite3.DatabaseError("database disk image is malformed"))
        self.assertIn("database disk image is malformed", detail)
        self.assertIn("path=", detail)
        self.assertIn("wal_exists=", detail)
        self.assertIn("shm_exists=", detail)

    def test_cli_diagnose_checkpoint_and_recover_plan(self) -> None:
        import json
        from click.testing import CliRunner
        from cairn.cli import main

        obs_path = Path(self.tmp.name).with_name("obs.sqlite")
        runner = CliRunner()

        diagnose = runner.invoke(
            main,
            [
                "db",
                "diagnose",
                "--db-path",
                self.tmp.name,
                "--observability-db-path",
                str(obs_path),
            ],
        )
        self.assertEqual(diagnose.exit_code, 0, diagnose.output)
        diagnose_payload = json.loads(diagnose.output)
        self.assertEqual(diagnose_payload["main"]["integrity_check"], ["ok"])
        self.assertIn("dispatcher_locks", diagnose_payload["main"])

        checkpoint = runner.invoke(
            main,
            [
                "db",
                "checkpoint",
                "--db-path",
                self.tmp.name,
                "--observability-db-path",
                str(obs_path),
            ],
        )
        self.assertEqual(checkpoint.exit_code, 0, checkpoint.output)
        checkpoint_payload = json.loads(checkpoint.output)
        self.assertIn("checkpoint", checkpoint_payload["main"])

        recover = runner.invoke(main, ["db", "recover-plan", "--db-path", self.tmp.name])
        self.assertEqual(recover.exit_code, 0, recover.output)
        recover_payload = json.loads(recover.output)
        self.assertIn("Stop cairn-dispatcher", recover_payload["steps"][0])


if __name__ == "__main__":
    unittest.main()
