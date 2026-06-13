from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")

from cairn.server import runtime_config
from helpers import reset_postgres_db

runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = _REPO / "dispatch.test.yaml"
runtime_config.reset_runtime_config_cache()


class DbMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def test_alembic_version_records_head(self) -> None:
        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            row = sql.fetchone(conn, "SELECT version_num FROM alembic_version")
            assert row is not None
        self.assertEqual(row["version_num"], "0003_add_scan_indexes")

    def test_core_indexes_exist(self) -> None:
        expected = {
            "idx_hints_project_id",
            "idx_intents_project_open_worker",
            "idx_intents_project_to_fact",
            "idx_intents_project_goal_once",
            "idx_intents_project_fact_once",
            "idx_intent_sources_project_fact",
            "idx_replay_steps_run_status",
            "idx_project_reason_state_retry",
            "idx_project_execution_configs_project",
            "idx_project_execution_ai_profiles_project_task",
            "idx_project_execution_capabilities_project_task",
            "idx_facts_project",
            "idx_llm_executions_started",
        }
        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            rows = sql.fetchall(
                conn,
                """
                SELECT indexname AS name
                FROM pg_indexes
                WHERE schemaname = 'public'
                """
            )
        names = {row["name"] for row in rows}
        self.assertTrue(expected.issubset(names), expected - names)

    def test_required_defaults_are_in_schema(self) -> None:
        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            rows = sql.fetchall(
                conn,
                """
                SELECT table_name, column_name, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND (table_name, column_name) IN (
                    ('intent_sources', 'position'),
                    ('ai_profile_check_requests', 'error_message')
                  )
                """
            )
        defaults = {(row["table_name"], row["column_name"]): row["column_default"] for row in rows}
        self.assertIn("0", defaults[("intent_sources", "position")])
        self.assertIn("''", defaults[("ai_profile_check_requests", "error_message")])


if __name__ == "__main__":
    unittest.main()
