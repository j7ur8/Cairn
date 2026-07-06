from __future__ import annotations

import json
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


class ExecutionConfigSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        self.yaml.__exit__(None, None, None)

    def test_project_create_writes_structured_execution_config_with_runtime_snapshot(self) -> None:
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilitySelection, CreateProjectRequest
        from cairn.server.schemas.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )

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
            task_timeouts=test_task_timeouts(explore_timeout=11, explore_conclude_timeout=12),
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

            timeout_rows = sql.fetchall(
                conn,
                """
                SELECT task_type, timeout, conclude_timeout
                FROM project_execution_task_timeouts
                WHERE project_id = :project_id
                ORDER BY task_type
                """,
                {"project_id": project.project.id},
            )
            ai_rows = sql.fetchall(
                conn,
                """
                SELECT task_type, profile_id, snapshot_model, snapshot_reasoning_type, snapshot_api_key_value
                FROM project_execution_ai_profiles
                WHERE project_id = :project_id
                ORDER BY task_type
                """,
                {"project_id": project.project.id},
            )
            header = sql.fetchone(
                conn,
                """
                SELECT prompts_json, prompts_sha256
                FROM project_execution_configs
                WHERE project_id = :project_id
                """,
                {"project_id": project.project.id},
            )
            removed_tables = sql.fetchall(
                conn,
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'worker_execution_configs',
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
            from cairn.server.execution_config import load_project_execution_config

            explore_config = load_project_execution_config(conn, project.project.id, "explore")

        self.assertEqual([row["task_type"] for row in timeout_rows], ["bootstrap", "explore", "reason"])
        self.assertEqual(next(row for row in timeout_rows if row["task_type"] == "explore")["timeout"], 11)
        self.assertEqual(next(row for row in timeout_rows if row["task_type"] == "explore")["conclude_timeout"], 12)
        self.assertEqual([row["task_type"] for row in ai_rows], ["bootstrap", "explore", "reason"])
        assert header is not None
        prompt_snapshot = json.loads(header["prompts_json"])
        self.assertEqual(prompt_snapshot["prompt_group"], "default")
        self.assertEqual(
            set(prompt_snapshot["prompts"]),
            {"bootstrap.md", "bootstrap_conclude.md", "explore.md", "explore_conclude.md", "reason.md", "FILE_OUTPUTS.md"},
        )
        self.assertEqual(header["prompts_sha256"], prompt_snapshot["prompts_sha256"])
        self.assertEqual(removed_tables, [])
        self.assertEqual(explore_config["task_type"], "explore")
        self.assertEqual(explore_config["task_timeout"], {"timeout": 11, "conclude_timeout": 12})
        self.assertIn("ai_profiles", explore_config)
        self.assertIn("config_revision", explore_config)
        self.assertEqual(explore_config["config_revision"]["prompts_sha256"], header["prompts_sha256"])
        self.assertEqual(explore_config["prompt_snapshot"], prompt_snapshot)
        self.assertIn("task_timeouts", explore_config)
        self.assertNotIn("sk", explore_config["ai_profiles"][0])
        self.assertEqual(explore_config["ai_profiles"][0]["snapshot_api_key_value"], "test-key")
        self.assertEqual(ai_rows[0]["snapshot_api_key_value"], "test-key")
        self.assertIn("container", explore_config)
        self.assertIn("workers", explore_config)
        self.assertNotIn("proxies", explore_config)
        self.assertNotIn("tool_proxy", explore_config)
        self.assertNotIn("tool_proxy_id", explore_config)
        self.assertNotIn("proxy", explore_config)
        self.assertNotIn("proxy_id", explore_config)
        self.assertIn("settings", explore_config)
        self.assertIn("catalog", explore_config)

    def test_execution_config_patch_route_is_not_available(self) -> None:
        import time

        import jwt
        from fastapi.testclient import TestClient

        from cairn.server.app import app
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilitySelection, CreateProjectRequest
        from cairn.server.schemas.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )
        from cairn.server.security.jwt import _JWT_ALGORITHM

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
            task_timeouts=test_task_timeouts(explore_timeout=11),
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

        token = jwt.encode(
            {
                "sub": "admin@cairn.local",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            os.environ["CAIRN_JWT_SECRET"],
            algorithm=_JWT_ALGORITHM,
        )
        with TestClient(app) as client:
            response = client.patch(
                f"/projects/{project.project.id}/execution-config",
                json={"task_timeouts": test_task_timeouts(explore_timeout=22).model_dump()},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 404)
        with self.db.session_scope() as conn:
            from cairn.server.execution_config import load_project_execution_config

            config = load_project_execution_config(conn, project.project.id, "explore")
        self.assertEqual(config["task_timeout"]["timeout"], 11)
        self.assertEqual(config["config_version"], 1)

    def test_persist_project_execution_config_rejects_existing_project_without_overwrite(self) -> None:
        from cairn.server.application.project_creation import ProjectCreationDraft, create_project_from_draft
        from cairn.server.domain.errors import ServerInvariantError
        from cairn.server.execution_config import load_project_execution_config, persist_project_execution_configs
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilitySelection, CreateProjectRequest
        from cairn.server.schemas.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )

        profile = create_ai_profile(AiProfileCreate(
            name="immutable-profile",
            worker_type="codex",
            model="gpt-original",
            api_key_env="OPENAI_API_KEY",
            sk="test-key",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="gpt-original",
            primary_reasoning_type="medium",
        )
        capabilities = {
            "bootstrap": CapabilitySelection(),
            "explore": CapabilitySelection(),
            "reason": CapabilitySelection(),
        }
        ai_profiles = TaskAiProfileSelections(
            bootstrap=selection,
            explore=selection,
            reason=selection,
        )
        project = create_project(CreateProjectRequest(
            title="immutable execution config",
            origin="origin",
            goal="goal",
            task_timeouts=test_task_timeouts(explore_timeout=11, explore_conclude_timeout=12),
            capabilities=capabilities,
            ai_profiles=ai_profiles,
        ))

        with self.db.session_scope() as conn:
            with self.assertRaisesRegex(ServerInvariantError, "project execution config already exists"):
                persist_project_execution_configs(
                    conn,
                    project.project.id,
                    capabilities=capabilities,
                    ai_profiles=ai_profiles,
                    role_id=None,
                    task_timeouts=test_task_timeouts(explore_timeout=99, explore_conclude_timeout=100),
                    now="2026-06-17T00:00:00Z",
                )

            explore_config = load_project_execution_config(conn, project.project.id, "explore")
            self.assertEqual(explore_config["task_timeout"], {"timeout": 11, "conclude_timeout": 12})
            self.assertEqual(explore_config["ai_profiles"][0]["snapshot_model"], "gpt-original")
            self.assertEqual(explore_config["capabilities"]["mcp_server_ids"], [])
            self.assertEqual(explore_config["capabilities"]["skill_ids"], [])
            self.assertEqual(explore_config["config_version"], 1)

            replay_project = create_project_from_draft(
                conn,
                ProjectCreationDraft(
                    project_id="proj_replay_config",
                    title="replay execution config",
                    origin="replay origin",
                    goal="replay goal",
                    capabilities=capabilities,
                    ai_profiles=ai_profiles,
                    task_timeouts=test_task_timeouts(explore_timeout=33, explore_conclude_timeout=34),
                    status="stopped",
                ),
            )
            replay_config = load_project_execution_config(conn, replay_project.project.id, "explore")
            source_config = load_project_execution_config(conn, project.project.id, "explore")
            self.assertEqual(replay_config["task_timeout"], {"timeout": 33, "conclude_timeout": 34})
            self.assertEqual(replay_config["config_version"], 1)
            self.assertEqual(source_config["task_timeout"], {"timeout": 11, "conclude_timeout": 12})

    def test_project_execution_config_assembly_uses_snapshot_not_current_yaml(self) -> None:
        import yaml

        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilitySelection, CreateProjectRequest
        from cairn.server.schemas.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )

        profile = create_ai_profile(AiProfileCreate(
            name="snap-profile",
            worker_type="codex",
            model="gpt-original",
            api_key_env="OPENAI_API_KEY",
            sk="original-secret",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="gpt-original",
            primary_reasoning_type="medium",
        )
        project = create_project(CreateProjectRequest(
            title="snapshot isolation",
            origin="origin",
            goal="goal",
            task_timeouts=test_task_timeouts(explore_timeout=11),
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

        data = yaml.safe_load(self.yaml.dispatch_path.read_text(encoding="utf-8"))
        data["worker_runtime"]["container"]["image"] = "cairn/changed:latest"
        data["server"]["settings"]["intent_timeout"] = 99
        data["worker_pool"]["workers"][0]["env"]["OPENAI_API_KEY"] = "changed-secret"
        self.yaml.dispatch_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        with self.db.session_scope() as conn:
            from cairn.server.execution_config import load_project_execution_config

            config = load_project_execution_config(conn, project.project.id, "explore")

        self.assertEqual(config["container"]["image"], "cairn/test:latest")
        self.assertEqual(config["settings"]["intent_timeout"], 5)
        self.assertEqual(config["ai_profiles"][0]["snapshot_api_key_value"], "original-secret")

    def test_create_project_request_requires_task_timeouts(self) -> None:
        from pydantic import ValidationError

        from cairn.server.schemas import CreateProjectRequest
        from cairn.server.schemas.ai_profiles import AiProfileSelection, TaskAiProfileSelections

        selection = AiProfileSelection(
            primary_profile_id="ai_test",
            primary_model="m",
            primary_reasoning_type="medium",
        )
        with self.assertRaises(ValidationError):
            CreateProjectRequest(
                title="missing timeouts",
                origin="origin",
                goal="goal",
                ai_profiles=TaskAiProfileSelections(
                    bootstrap=selection,
                    explore=selection,
                    reason=selection,
                ),
            )

    def test_assembled_execution_config_includes_capability_snapshots(self) -> None:
        import yaml

        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilitySelection, CreateProjectRequest
        from cairn.server.schemas.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )

        skill_dir = self.yaml.root / "ctf-web-js-analysis"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# CTF Web JS Analysis\n", encoding="utf-8")
        self.yaml.capabilities_path.write_text(
            yaml.safe_dump(
                {
                    "capabilities": {
                        "mcp_servers": [
                            {
                                "id": "js-reverse-mcp-cloak",
                                "name": "JS Reverse Cloak",
                                "transport": "stdio",
                                "command": "js-reverse-mcp-cairn",
                                "task_types": ["bootstrap", "explore"],
                            }
                        ],
                        "skills": [
                            {
                                "id": "ctf-web-js-analysis",
                                "name": "CTF Web JS Analysis",
                                "source_path": str(skill_dir),
                                "task_types": ["bootstrap", "explore"],
                            }
                        ],
                    },
                    "roles": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        profile = create_ai_profile(AiProfileCreate(
            name="snapshot-profile",
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
            title="capability snapshots",
            origin="origin",
            goal="goal",
            task_timeouts=test_task_timeouts(),
            capabilities={
                "bootstrap": CapabilitySelection(
                    mcp_server_ids=["js-reverse-mcp-cloak"],
                    skill_ids=["ctf-web-js-analysis"],
                ),
                "explore": CapabilitySelection(
                    mcp_server_ids=["js-reverse-mcp-cloak"],
                    skill_ids=["ctf-web-js-analysis"],
                ),
                "reason": CapabilitySelection(),
            },
            ai_profiles=TaskAiProfileSelections(
                bootstrap=selection,
                explore=selection,
                reason=selection,
            ),
        ))

        with self.db.session_scope() as conn:
            from cairn.server.execution_config import load_project_execution_config, load_project_execution_configs

            bootstrap_config = load_project_execution_config(conn, project.project.id, "bootstrap")
            configs = load_project_execution_configs(conn, project.project.id)

        expected = [
            {"kind": "mcp_server", "capability_id": "js-reverse-mcp-cloak", "source": "selected"},
            {"kind": "skill", "capability_id": "ctf-web-js-analysis", "source": "selected"},
        ]
        self.assertEqual(bootstrap_config["capabilities"]["snapshots"], expected)
        self.assertEqual(configs["explore"]["capabilities"]["snapshots"], expected)
        self.assertEqual(configs["reason"]["capabilities"]["snapshots"], [])


if __name__ == "__main__":
    unittest.main()
