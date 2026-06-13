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

from helpers import TempYamlConfig, reset_postgres_db, test_task_timeouts


class AiProfileFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        self.yaml.__exit__(None, None, None)

    def test_crud_uses_dispatch_yaml(self) -> None:
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate, AiProfileUpdate
        from cairn.server.routers.ai_profiles import (
            create_ai_profile,
            delete_ai_profile,
            get_ai_profile,
            list_ai_profiles,
            update_ai_profile,
        )

        created = create_ai_profile(AiProfileCreate(
            name="gpt-deepseek",
            worker_type="codex",
            model="deepseek-coder",
            api_key_env="DEEPSEEK_KEY",
            sk="sk-test",
        ))
        self.assertTrue(created.id.startswith("ai_"))
        self.assertEqual(created.api_key_env, "OPENAI_API_KEY")
        self.assertEqual(created.sk_preview, "***test")
        self.assertEqual(len(list_ai_profiles()), 1)

        fetched = get_ai_profile(created.id)
        self.assertEqual(fetched.id, created.id)

        updated = update_ai_profile(
            created.id,
            AiProfileUpdate(
                model="deepseek-v3",
                models=["deepseek-v3", "deepseek-reasoner"],
                base_url="https://api.example/v1",
                model_reasoning_effort="xhigh",
            ),
        )
        self.assertEqual(updated.model, "deepseek-v3")
        self.assertEqual(updated.models, ["deepseek-reasoner", "deepseek-v3"])
        self.assertEqual(updated.model_reasoning_effort, "xhigh")

        delete_ai_profile(created.id)
        self.assertEqual(list_ai_profiles(), [])

    def test_project_ai_selection_round_trips_from_execution_config(self) -> None:
        from cairn.server.models_pkg import CreateProjectRequest
        from cairn.server.models_pkg.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )
        from cairn.server.routers.ai_profiles import create_ai_profile, get_project_ai_profiles
        from cairn.server.routers.projects import create_project

        boot = create_ai_profile(AiProfileCreate(
            name="boot", worker_type="codex", model="m1", api_key_env="K1", sk="sk-1",
        ))
        explore = create_ai_profile(AiProfileCreate(
            name="explore", worker_type="codex", model="m2", api_key_env="K2", sk="sk-2",
        ))
        reason = create_ai_profile(AiProfileCreate(
            name="reason", worker_type="claudecode", model="m3", api_key_env="K3", sk="sk-3",
        ))

        project = create_project(CreateProjectRequest(
            title="P-task-ai",
            origin="origin",
            goal="goal",
            task_timeouts=test_task_timeouts(),
            ai_profiles=TaskAiProfileSelections(
                bootstrap=AiProfileSelection(
                    primary_profile_id=boot.id,
                    primary_model="m1",
                    primary_reasoning_type="low",
                ),
                explore=AiProfileSelection(
                    primary_profile_id=explore.id,
                    primary_model="m2",
                    primary_reasoning_type="medium",
                ),
                reason=AiProfileSelection(
                    primary_profile_id=reason.id,
                    primary_model="m3",
                    primary_reasoning_type="high",
                    fallback_profile_ids=[boot.id],
                ),
            ),
        ))

        result = get_project_ai_profiles(project.project.id)
        self.assertEqual(result.selections.bootstrap.primary_profile_id, boot.id)
        self.assertEqual(result.selections.explore.primary_profile_id, explore.id)
        self.assertEqual(result.selections.reason.primary_profile_id, reason.id)
        self.assertEqual(result.selections.reason.fallback_profile_ids, [boot.id])
        self.assertEqual({snap.task_type for snap in result.snapshots}, {"bootstrap", "explore", "reason"})
        primary_envs = {snap.task_type: snap.snapshot_api_key_env for snap in result.snapshots if snap.role == "primary"}
        self.assertEqual(primary_envs["bootstrap"], "OPENAI_API_KEY")
        self.assertEqual(primary_envs["explore"], "OPENAI_API_KEY")
        self.assertEqual(primary_envs["reason"], "ANTHROPIC_AUTH_TOKEN")

    def test_complete_task_selection_required(self) -> None:
        from fastapi import HTTPException

        from cairn.server.ai_profile_service import require_complete_ai_profile_selections
        from cairn.server.models_pkg.ai_profiles import AiProfileSelection, TaskAiProfileSelections

        with self.assertRaises(HTTPException):
            require_complete_ai_profile_selections(None)

        with self.assertRaises(HTTPException) as ctx:
            require_complete_ai_profile_selections(
                TaskAiProfileSelections(
                    bootstrap=AiProfileSelection(
                        primary_profile_id="ai_boot",
                        primary_model="m1",
                        primary_reasoning_type="low",
                    ),
                    explore=AiProfileSelection(
                        primary_profile_id="ai_explore",
                        primary_model="m2",
                        primary_reasoning_type="medium",
                    ),
                )
            )
        self.assertIn("reason", ctx.exception.detail)

    def test_invalid_selected_model_rejected_on_project_create(self) -> None:
        from fastapi import HTTPException

        from cairn.server.models_pkg import CreateProjectRequest
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate, AiProfileSelection, TaskAiProfileSelections
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project

        profile = create_ai_profile(AiProfileCreate(
            name="codex", worker_type="codex", model="default-model", api_key_env="K1", sk="test-key",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="not-available",
            primary_reasoning_type="medium",
        )
        with self.assertRaises(HTTPException) as ctx:
            create_project(CreateProjectRequest(
                title="P-invalid-model",
                origin="origin",
                goal="goal",
                task_timeouts=test_task_timeouts(),
                ai_profiles=TaskAiProfileSelections(
                    bootstrap=selection,
                    explore=selection,
                    reason=selection,
                ),
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not available", ctx.exception.detail)

    def test_deleted_profile_marks_existing_snapshot_unavailable(self) -> None:
        from cairn.server.models_pkg import CreateProjectRequest
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate, AiProfileSelection, TaskAiProfileSelections
        from cairn.server.routers.ai_profiles import create_ai_profile, delete_ai_profile, get_project_ai_profiles
        from cairn.server.routers.projects import create_project

        profile = create_ai_profile(AiProfileCreate(
            name="to-delete", worker_type="codex", model="m", api_key_env="K", sk="test-key",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="m",
            primary_reasoning_type="medium",
        )
        project = create_project(CreateProjectRequest(
            title="P",
            origin="origin",
            goal="goal",
            task_timeouts=test_task_timeouts(),
            ai_profiles=TaskAiProfileSelections(
                bootstrap=selection,
                explore=selection,
                reason=selection,
            ),
        ))
        delete_ai_profile(profile.id)

        result = get_project_ai_profiles(project.project.id)
        self.assertEqual(len(result.snapshots), 3)
        self.assertIn(profile.id, result.unavailable_profile_ids)


if __name__ == "__main__":
    unittest.main()
