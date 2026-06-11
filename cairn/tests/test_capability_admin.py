from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_DISABLE_DISPATCHER_RELOAD", "1")

from helpers import TempYamlConfig, reset_postgres_db, test_task_timeouts


class CapabilityAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        self.yaml.__exit__(None, None, None)

    def _create_profile_selection(self):
        from cairn.server.models_pkg.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )
        from cairn.server.routers.ai_profiles import create_ai_profile

        profile = create_ai_profile(AiProfileCreate(
            name="t",
            worker_type="codex",
            model="m",
            api_key_env="OPENAI_API_KEY",
            sk="test-key",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="m",
            primary_reasoning_type="medium",
        )
        return TaskAiProfileSelections(bootstrap=selection, explore=selection, reason=selection)

    def test_admin_upsert_and_delete_uses_capabilities_yaml(self) -> None:
        from cairn.server.models_pkg.capabilities import CapabilityAdminRequest
        from cairn.server.routers.capabilities import (
            delete_admin_capability,
            get_capability_catalog,
            upsert_admin_capability,
        )

        upsert_admin_capability("mcp_server", "my-mcp", CapabilityAdminRequest(
            id="my-mcp",
            name="My MCP",
            task_types=["bootstrap", "explore"],
            transport="stdio",
            command="my-mcp",
        ))
        upsert_admin_capability("skill", "my-skill", CapabilityAdminRequest(
            id="my-skill",
            name="My Skill",
            task_types=["bootstrap"],
            source_path="/tmp/my-skill",
        ))

        items = {(item.kind, item.id): item for item in get_capability_catalog()}
        self.assertIn(("mcp_server", "my-mcp"), items)
        self.assertIn(("skill", "my-skill"), items)

        delete_admin_capability("skill", "my-skill")
        items = {(item.kind, item.id): item for item in get_capability_catalog()}
        self.assertIn(("mcp_server", "my-mcp"), items)
        self.assertNotIn(("skill", "my-skill"), items)

    def test_expansion_auto_adds_required_skill(self) -> None:
        from cairn.server.capabilities_service import (
            catalog_map_from_items,
            expand_task_capabilities,
        )
        from cairn.server.models_pkg.capabilities import CapabilityAdminRequest, task_capabilities_map
        from cairn.server.routers.capabilities import get_capability_catalog, upsert_admin_capability

        upsert_admin_capability("skill", "a", CapabilityAdminRequest(
            id="a",
            name="A",
            task_types=["bootstrap"],
            source_path="/tmp/a",
        ))
        upsert_admin_capability("mcp_server", "m", CapabilityAdminRequest(
            id="m",
            name="M",
            task_types=["bootstrap"],
            transport="stdio",
            command="m",
            required_skill_ids=["a"],
        ))
        per_task = task_capabilities_map({
            "bootstrap": {
                "mcp_server_ids": ["m"],
                "user_mcp_server_ids": ["m"],
            },
        })

        catalog = catalog_map_from_items(get_capability_catalog())
        expanded, errors = expand_task_capabilities(per_task, catalog)
        self.assertEqual(errors, [])
        self.assertEqual(expanded["bootstrap"].mcp_server_ids, ["m"])
        self.assertEqual(expanded["bootstrap"].skill_ids, ["a"])
        self.assertEqual(expanded["bootstrap"].user_skill_ids, [])

    def test_project_create_persists_role_default_skill_in_execution_config(self) -> None:
        from cairn.server.models_pkg.capabilities import CapabilityAdminRequest
        from cairn.server.models_pkg.intents import CreateProjectRequest
        from cairn.server.routers.capabilities import get_project_capabilities, upsert_admin_capability
        from cairn.server.routers.projects import create_project
        import yaml

        skill_dir = self.yaml.root / "role-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Role Skill\n", encoding="utf-8")
        upsert_admin_capability("skill", "role-skill", CapabilityAdminRequest(
            id="role-skill",
            name="Role Skill",
            task_types=["bootstrap", "explore"],
            source_path=str(skill_dir),
        ))
        data = yaml.safe_load(self.yaml.capabilities_path.read_text(encoding="utf-8"))
        data["roles"] = [
            {
                "id": "role1",
                "name": "Role",
                "prompt": "prompt",
                "default_skill_ids": ["role-skill"],
                "task_types": ["bootstrap", "explore", "reason"],
            }
        ]
        self.yaml.capabilities_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        project = create_project(CreateProjectRequest(
            title="p",
            origin="o",
            goal="g",
            role_id="role1",
            task_timeouts=test_task_timeouts(),
            ai_profiles=self._create_profile_selection(),
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
        self.assertEqual([row["task_type"] for row in rows], ["bootstrap", "explore", "reason"])
        bootstrap_config = json.loads(rows[0]["config_json"])
        self.assertEqual(bootstrap_config["capabilities"]["skill_ids"], ["role-skill"])
        self.assertEqual(bootstrap_config["capabilities"]["role_default_skill_ids"], ["role-skill"])

        response = get_project_capabilities(project.project.id)
        boot_snapshots = response.tasks["bootstrap"].snapshots
        self.assertEqual(boot_snapshots[0].capability_id, "role-skill")
        self.assertEqual(boot_snapshots[0].source, "role_default")

    def test_probe_stdio_command_without_source_path_is_ok(self) -> None:
        from cairn.server.models_pkg.capabilities import CapabilityAdminRequest
        from cairn.server.routers.capabilities import probe_admin_capability, upsert_admin_capability

        upsert_admin_capability("mcp_server", "stdio-mcp", CapabilityAdminRequest(
            id="stdio-mcp",
            name="Stdio MCP",
            task_types=["explore"],
            transport="stdio",
            command="/usr/local/bin/mcp-server",
        ))
        entry = probe_admin_capability("mcp_server", "stdio-mcp")
        self.assertEqual(entry.status, "ok")
        self.assertEqual(entry.message, "stdio command configured")

    def test_probe_chrome_devtools_http_reports_reachable(self) -> None:
        from cairn.server.models_pkg.capabilities import CapabilityAdminRequest
        from cairn.server.routers.capabilities import probe_admin_capability, upsert_admin_capability

        upsert_admin_capability("mcp_server", "chrome-devtools-host", CapabilityAdminRequest(
            id="chrome-devtools-host",
            name="Host Chrome",
            task_types=["bootstrap"],
            transport="stdio",
            command="chrome-devtools-mcp",
            probe_config={
                "type": "chrome_devtools_http",
                "url": "http://host.docker.internal:9222/json/version",
            },
        ))
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/browser/abc"}'
        with patch("socket.gethostbyname", return_value="0.250.250.254"), patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            entry = probe_admin_capability("mcp_server", "chrome-devtools-host")
        self.assertEqual(entry.status, "ok")
        self.assertEqual(entry.message, "chrome devtools endpoint reachable")
        self.assertEqual(mock_urlopen.call_args.args[0], "http://0.250.250.254:9222/json/version")


class DispatcherConfigRequiredSkillIdsTests(unittest.TestCase):
    def test_yaml_mcp_required_skill_must_resolve(self) -> None:
        from cairn.shared.dispatch_config import (
            CapabilitiesConfig,
            McpServerCapabilityConfig,
            SkillCapabilityConfig,
        )
        from pydantic import ValidationError

        with self.assertRaises(ValidationError) as ctx:
            CapabilitiesConfig(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="m",
                        name="M",
                        transport="stdio",
                        command="m",
                        required_skill_ids=["ghost"],
                    ),
                ],
                skills=[
                    SkillCapabilityConfig(id="a", name="A", source_path="/tmp/a"),
                ],
            )
        self.assertIn("ghost", str(ctx.exception))

    def test_yaml_skill_preferred_mcp_must_resolve(self) -> None:
        from cairn.shared.dispatch_config import CapabilitiesConfig, SkillCapabilityConfig
        from pydantic import ValidationError

        with self.assertRaises(ValidationError) as ctx:
            CapabilitiesConfig(
                skills=[
                    SkillCapabilityConfig(
                        id="a",
                        name="A",
                        source_path="/tmp/a",
                        preferred_mcp_ids=["ghost-mcp"],
                    ),
                ],
            )
        self.assertIn("ghost-mcp", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
