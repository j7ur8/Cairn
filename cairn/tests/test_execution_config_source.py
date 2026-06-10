from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_DISABLE_DISPATCHER_RELOAD", "1")

from helpers import TempYamlConfig


class ExecutionConfigSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        from cairn.server import db

        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        db.reset_for_tests()
        from cairn.server.runtime_config import system_config
        db.configure(system_config().database.url, run_migrations=False)
        db.drop_all_for_tests()
        db.upgrade_head()
        db.seed_defaults()
        self.db = db

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        self.yaml.__exit__(None, None, None)

    def test_project_create_writes_only_execution_configs(self) -> None:
        from cairn.server.models_pkg.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )
        from cairn.server.models_pkg.capabilities import CapabilitySelection
        from cairn.server.models_pkg.intents import CreateProjectRequest
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project

        profile = create_ai_profile(AiProfileCreate(
            name="exec-profile",
            worker_type="codex",
            model="gpt-test",
            api_key_env="OPENAI_API_KEY",
            sk="test-key",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="gpt-test",
            primary_reasoning_type="medium",
        )
        project = create_project(CreateProjectRequest(
            title="execution source",
            origin="origin",
            goal="goal",
            capabilities={
                "bootstrap": CapabilitySelection(),
                "explore": CapabilitySelection(),
                "reason": CapabilitySelection(),
            },
            ai_profiles=TaskAiProfileSelections(
                bootstrap=selection,
                explore=selection,
                reason=selection,
            ),
        ))

        with self.db.session_scope() as conn:
            from cairn.server.repositories import sql

            rows = sql.fetchall(
                conn,
                """
                SELECT task_type, config_json
                FROM worker_execution_configs
                WHERE project_id = :project_id
                ORDER BY task_type
                """,
                {"project_id": project.project.id},
            )
            legacy_tables = sql.fetchall(
                conn,
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'project_ai_profiles',
                    'project_capability_snapshots',
                    'project_capabilities',
                    'project_roles',
                    'capability_catalog',
                    'role_catalog',
                    'ai_profiles',
                    'ai_profile_models'
                  )
                """
            )

        self.assertEqual([row["task_type"] for row in rows], ["bootstrap", "explore", "reason"])
        self.assertEqual(legacy_tables, [])
        self.assertIn('"ai_profiles"', rows[0]["config_json"])
        self.assertIn('"config_revision"', rows[0]["config_json"])


if __name__ == "__main__":
    unittest.main()
