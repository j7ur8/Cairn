from __future__ import annotations

import os
import json
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
        self.tmp = tempfile.NamedTemporaryFile(suffix=".pgtest", delete=False)
        self.tmp.close()
        from cairn.server import db

        db.reset_for_tests()
        db.configure(Path(self.tmp.name))
        self.db = db

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def _project_ai_profiles(self):
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

    def _cli_json(self, output: str) -> dict:
        return json.loads(output[output.rfind("{"):])

    def test_get_conn_returns_working_sqlalchemy_adapter(self) -> None:
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT 1 AS ok").fetchone()
        self.assertEqual(row["ok"], 1)

    def test_connections_work_across_threads(self) -> None:
        results: list[int] = []

        def worker() -> None:
            with self.db.get_conn() as conn:
                results.append(conn.execute("SELECT 1 AS ok").fetchone()["ok"])

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [1, 1])

    def test_with_immediate_tx_commits(self) -> None:
        with self.db.with_immediate_tx() as conn:
            conn.execute(
                "INSERT INTO users (id, email, hashed_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("u1", "a@example.com", "x", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT email FROM users WHERE id = 'u1'").fetchone()
        self.assertEqual(row["email"], "a@example.com")

    def test_postgres_status_is_available(self) -> None:
        status = self.db.postgres_status()
        self.assertEqual(status["database"], "postgresql")
        self.assertTrue(status["ok"])

    def test_state_uniqueness_indexes_exist(self) -> None:
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT indexname AS name
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'intents'
                  AND indexname IN ('idx_intents_project_goal_once', 'idx_intents_project_fact_once')
                """
            ).fetchall()
        self.assertEqual(
            {row["name"] for row in rows},
            {"idx_intents_project_goal_once", "idx_intents_project_fact_once"},
        )

    def test_concurrent_conclude_produces_one_fact(self) -> None:
        from cairn.server.models import ConcludeRequest, CreateIntentRequest, CreateProjectRequest
        from cairn.server.routers.intents import conclude, create_intent
        from cairn.server.routers.projects import create_project

        project = create_project(
            CreateProjectRequest(
                title="p",
                origin="o",
                goal="g",
                ai_profiles=self._project_ai_profiles(),
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
                ai_profiles=self._project_ai_profiles(),
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

    def test_cli_status_migrate_and_reset(self) -> None:
        import json
        from click.testing import CliRunner
        from cairn.cli import main

        runner = CliRunner()

        status = runner.invoke(main, ["db", "status"])
        self.assertEqual(status.exit_code, 0, status.output)
        self.assertEqual(json.loads(status.output)["status"]["database"], "postgresql")

        migrate = runner.invoke(main, ["db", "migrate"])
        self.assertEqual(migrate.exit_code, 0, migrate.output)
        self.assertEqual(self._cli_json(migrate.output)["database"], "postgresql")

        reset = runner.invoke(main, ["db", "reset", "--yes"])
        self.assertEqual(reset.exit_code, 0, reset.output)
        self.assertEqual(self._cli_json(reset.output)["database"], "postgresql")


if __name__ == "__main__":
    unittest.main()
