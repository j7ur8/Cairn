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
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.schemas.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )

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

    def _write_cairn_resources_capability(self, *, available: bool = True, include_other: bool = False) -> None:
        import yaml

        mcp_servers = [
            {
                "id": "cairn-resources",
                "name": "Cairn Resources MCP",
                "transport": "stdio",
                "command": "/usr/local/bin/cairn-resources-mcp-stdio",
                "task_types": ["bootstrap", "explore"],
                "available": available,
            }
        ]
        if include_other:
            mcp_servers.append(
                {
                    "id": "other-mcp",
                    "name": "Other MCP",
                    "transport": "stdio",
                    "command": "/usr/local/bin/other-mcp",
                    "task_types": ["bootstrap"],
                    "available": True,
                }
            )
        data = {"capabilities": {"mcp_servers": mcp_servers, "skills": []}, "roles": []}
        self.yaml.capabilities_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def test_admin_upsert_and_delete_uses_capabilities_yaml(self) -> None:
        from cairn.server.routers.capabilities import (
            delete_admin_capability,
            get_capability_catalog,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

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
        self.assertEqual(items[("mcp_server", "my-mcp")].source, "user")
        self.assertEqual(items[("skill", "my-skill")].source, "user")

        delete_admin_capability("skill", "my-skill")
        items = {(item.kind, item.id): item for item in get_capability_catalog()}
        self.assertIn(("mcp_server", "my-mcp"), items)
        self.assertNotIn(("skill", "my-skill"), items)

    def test_admin_upsert_persists_mcp_env(self) -> None:
        from cairn.server.routers.capabilities import get_capability_catalog, upsert_admin_capability
        from cairn.server.schemas import CapabilityAdminRequest

        upsert_admin_capability("mcp_server", "env-mcp", CapabilityAdminRequest(
            id="env-mcp",
            name="Env MCP",
            task_types=["bootstrap", "explore"],
            transport="stdio",
            command="env-mcp",
            env={"A": "1", "B": "two"},
        ))

        items = {(item.kind, item.id): item for item in get_capability_catalog()}
        self.assertEqual(items[("mcp_server", "env-mcp")].env, {"A": "1", "B": "two"})

    def test_admin_upsert_persists_mcp_runtime_provider(self) -> None:
        import yaml

        from cairn.server.routers.capabilities import get_capability_catalog, upsert_admin_capability
        from cairn.server.schemas import CapabilityAdminRequest

        upsert_admin_capability("mcp_server", "browser-mcp", CapabilityAdminRequest(
            id="browser-mcp",
            name="Browser MCP",
            task_types=["explore"],
            transport="stdio",
            command="/usr/local/bin/cairn-browser-mcp",
            args=["js-reverse-mcp", "--browserUrl", "{browser_url}"],
            runtime_provider={"type": "cloak_sidecar", "resource": "browser_url"},
        ))

        items = {(item.kind, item.id): item for item in get_capability_catalog()}
        self.assertEqual(
            items[("mcp_server", "browser-mcp")].runtime_provider,
            {"type": "cloak_sidecar", "resource": "browser_url"},
        )
        data = yaml.safe_load(self.yaml.capabilities_path.read_text(encoding="utf-8"))
        self.assertEqual(
            data["capabilities"]["mcp_servers"][0]["runtime_provider"],
            {"type": "cloak_sidecar", "resource": "browser_url"},
        )

    def test_import_mcp_json_creates_user_items(self) -> None:
        from cairn.server.routers.capabilities import get_capability_catalog, import_admin_mcp_json
        from cairn.server.schemas import McpImportRequest

        result = import_admin_mcp_json(McpImportRequest(mcpServers={
            "remote-http": {
                "url": "https://example.test/mcp",
                "headers": {"Authorization": "Bearer x"},
            },
            "local-stdio": {
                "command": "/usr/local/bin/example-mcp",
                "args": ["--flag"],
                "env": {"K": "V"},
            },
        }))

        self.assertEqual(sorted(result.created), ["local-stdio", "remote-http"])
        items = {(item.kind, item.id): item for item in get_capability_catalog()}
        self.assertEqual(items[("mcp_server", "remote-http")].transport, "http")
        self.assertEqual(items[("mcp_server", "remote-http")].source, "user")
        self.assertEqual(items[("mcp_server", "local-stdio")].env, {"K": "V"})

    def test_import_mcp_json_rejects_builtin_conflict(self) -> None:
        from cairn.server.routers.capabilities import import_admin_mcp_json
        from cairn.server.schemas import McpImportRequest

        result = import_admin_mcp_json(McpImportRequest(mcpServers={
            "kali-server-mcp": {"command": "other"},
        }))

        self.assertEqual(result.conflicts, ["kali-server-mcp"])

    def test_skill_source_path_is_required(self) -> None:
        from fastapi import HTTPException

        from cairn.server.routers.capabilities import upsert_admin_capability
        from cairn.server.schemas import CapabilityAdminRequest

        with self.assertRaises(HTTPException) as cm:
            upsert_admin_capability("skill", "missing-path", CapabilityAdminRequest(
                id="missing-path",
                name="Missing Path",
                task_types=["bootstrap"],
                source_path="",
            ))

        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("source_path", cm.exception.detail)

    def test_expansion_auto_adds_required_skill(self) -> None:
        from cairn.server.capability_expansion import (
            catalog_map_from_items,
            expand_task_capabilities,
        )
        from cairn.server.routers.capabilities import get_capability_catalog, upsert_admin_capability
        from cairn.server.schemas import CapabilityAdminRequest, task_capabilities_map

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
        import yaml

        from cairn.server.routers.capabilities import get_project_capabilities, upsert_admin_capability
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilityAdminRequest, CreateProjectRequest

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
            from cairn.server.execution_config import load_project_execution_config

            bootstrap_config = load_project_execution_config(conn, project.project.id, "bootstrap")
        self.assertEqual(bootstrap_config["capabilities"]["skill_ids"], ["role-skill"])
        self.assertEqual(bootstrap_config["capabilities"]["role_default_skill_ids"], ["role-skill"])

        response = get_project_capabilities(project.project.id)
        boot_snapshots = response.tasks["bootstrap"].snapshots
        self.assertEqual(boot_snapshots[0].capability_id, "role-skill")
        self.assertEqual(boot_snapshots[0].source, "role_default")

    def test_project_create_defaults_cairn_resources_for_bootstrap_and_explore(self) -> None:
        from cairn.server.routers.capabilities import get_project_capabilities
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CreateProjectRequest

        self._write_cairn_resources_capability()

        project = create_project(CreateProjectRequest(
            title="p",
            origin="o",
            goal="g",
            task_timeouts=test_task_timeouts(),
            ai_profiles=self._create_profile_selection(),
        ))

        with self.db.session_scope() as conn:
            from cairn.server.execution_config import load_project_execution_config

            bootstrap_config = load_project_execution_config(conn, project.project.id, "bootstrap")
            explore_config = load_project_execution_config(conn, project.project.id, "explore")
            reason_config = load_project_execution_config(conn, project.project.id, "reason")
        self.assertEqual(bootstrap_config["capabilities"]["mcp_server_ids"], ["cairn-resources"])
        self.assertEqual(bootstrap_config["capabilities"]["user_mcp_server_ids"], ["cairn-resources"])
        self.assertEqual(explore_config["capabilities"]["mcp_server_ids"], ["cairn-resources"])
        self.assertEqual(reason_config["capabilities"]["mcp_server_ids"], [])

        response = get_project_capabilities(project.project.id)
        self.assertEqual(
            [item.capability_id for item in response.tasks["bootstrap"].snapshots],
            ["cairn-resources"],
        )
        self.assertEqual(response.tasks["bootstrap"].snapshots[0].source, "selected")
        self.assertEqual(response.tasks["reason"].snapshots, [])

    def test_project_create_adds_cairn_resources_alongside_explicit_mcp_selection(self) -> None:
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilitySelection, CreateProjectRequest

        self._write_cairn_resources_capability(include_other=True)

        project = create_project(CreateProjectRequest(
            title="p",
            origin="o",
            goal="g",
            capabilities={
                "bootstrap": CapabilitySelection(mcp_server_ids=["other-mcp"]),
                "explore": CapabilitySelection(),
                "reason": CapabilitySelection(),
            },
            task_timeouts=test_task_timeouts(),
            ai_profiles=self._create_profile_selection(),
        ))

        with self.db.session_scope() as conn:
            from cairn.server.execution_config import load_project_execution_config

            bootstrap_config = load_project_execution_config(conn, project.project.id, "bootstrap")
            explore_config = load_project_execution_config(conn, project.project.id, "explore")
            reason_config = load_project_execution_config(conn, project.project.id, "reason")
        self.assertEqual(bootstrap_config["capabilities"]["mcp_server_ids"], ["other-mcp", "cairn-resources"])
        self.assertEqual(bootstrap_config["capabilities"]["user_mcp_server_ids"], ["other-mcp", "cairn-resources"])
        self.assertEqual(explore_config["capabilities"]["mcp_server_ids"], ["cairn-resources"])
        self.assertEqual(reason_config["capabilities"]["mcp_server_ids"], [])

    def test_project_create_does_not_default_unavailable_cairn_resources(self) -> None:
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CreateProjectRequest

        self._write_cairn_resources_capability(available=False)

        project = create_project(CreateProjectRequest(
            title="p",
            origin="o",
            goal="g",
            task_timeouts=test_task_timeouts(),
            ai_profiles=self._create_profile_selection(),
        ))

        with self.db.session_scope() as conn:
            from cairn.server.execution_config import load_project_execution_config

            bootstrap_config = load_project_execution_config(conn, project.project.id, "bootstrap")
            explore_config = load_project_execution_config(conn, project.project.id, "explore")
        self.assertEqual(bootstrap_config["capabilities"]["mcp_server_ids"], [])
        self.assertEqual(explore_config["capabilities"]["mcp_server_ids"], [])

    def test_project_capability_audit_reports_cairn_resources_snapshot_and_catalog(self) -> None:
        import yaml

        from cairn.server.routers.capabilities import get_project_capability_audit
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CreateProjectRequest

        self.yaml.capabilities_path.write_text(
            yaml.safe_dump({"capabilities": {"mcp_servers": [], "skills": []}, "roles": []}, sort_keys=False),
            encoding="utf-8",
        )
        project = create_project(CreateProjectRequest(
            title="legacy",
            origin="o",
            goal="g",
            task_timeouts=test_task_timeouts(),
            ai_profiles=self._create_profile_selection(),
        ))

        self._write_cairn_resources_capability()
        audit = get_project_capability_audit(project.project.id)

        self.assertEqual(audit.project_id, project.project.id)
        self.assertEqual(audit.mcp_server_id, "cairn-resources")
        self.assertTrue(audit.catalog.present)
        self.assertTrue(audit.catalog.available)
        self.assertTrue(audit.catalog.supports_bootstrap)
        self.assertTrue(audit.catalog.supports_explore)
        self.assertFalse(audit.tasks["bootstrap"].has_cairn_resources)
        self.assertFalse(audit.tasks["explore"].has_cairn_resources)
        self.assertFalse(audit.tasks["reason"].has_cairn_resources)

    def test_project_capabilities_query_uses_execution_config_catalog_snapshot(self) -> None:
        from cairn.server.routers.capabilities import (
            get_project_capabilities,
            get_capability_catalog,
            upsert_admin_capability,
        )
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilityAdminRequest, CapabilitySelection, CreateProjectRequest

        upsert_admin_capability("mcp_server", "snap-mcp", CapabilityAdminRequest(
            id="snap-mcp",
            name="Snapshot MCP",
            task_types=["bootstrap"],
            transport="stdio",
            command="snap-mcp",
        ))
        project = create_project(CreateProjectRequest(
            title="p",
            origin="o",
            goal="g",
            capabilities={
                "bootstrap": CapabilitySelection(mcp_server_ids=["snap-mcp"]),
                "explore": CapabilitySelection(),
                "reason": CapabilitySelection(),
            },
            task_timeouts=test_task_timeouts(),
            ai_profiles=self._create_profile_selection(),
        ))
        upsert_admin_capability("mcp_server", "snap-mcp", CapabilityAdminRequest(
            id="snap-mcp",
            name="Renamed MCP",
            task_types=["bootstrap"],
            transport="stdio",
            command="snap-mcp",
        ))

        self.assertEqual(
            next(item for item in get_capability_catalog() if item.id == "snap-mcp").name,
            "Renamed MCP",
        )
        response = get_project_capabilities(project.project.id)
        self.assertEqual(
            next(item for item in response.catalog if item.id == "snap-mcp").name,
            "Snapshot MCP",
        )
        self.assertEqual(response.unavailable, {"mcp_server_ids": [], "skill_ids": []})

    def test_project_capabilities_query_falls_back_to_yaml_catalog_for_legacy_rows(self) -> None:
        from cairn.server.repositories import sql
        from cairn.server.routers.capabilities import get_project_capabilities, upsert_admin_capability
        from cairn.server.routers.projects import create_project
        from cairn.server.schemas import CapabilityAdminRequest, CapabilitySelection, CreateProjectRequest

        upsert_admin_capability("skill", "legacy-skill", CapabilityAdminRequest(
            id="legacy-skill",
            name="Legacy Skill",
            task_types=["bootstrap"],
            source_path="/tmp/legacy-skill",
        ))
        project = create_project(CreateProjectRequest(
            title="p",
            origin="o",
            goal="g",
            capabilities={
                "bootstrap": CapabilitySelection(skill_ids=["legacy-skill"]),
                "explore": CapabilitySelection(),
                "reason": CapabilitySelection(),
            },
            task_timeouts=test_task_timeouts(),
            ai_profiles=self._create_profile_selection(),
        ))
        with self.db.session_scope() as conn:
            sql.execute(
                conn,
                "UPDATE project_execution_configs SET catalog_json = NULL WHERE project_id = :project_id",
                {"project_id": project.project.id},
            )

        response = get_project_capabilities(project.project.id)
        self.assertEqual(
            next(item for item in response.catalog if item.id == "legacy-skill").name,
            "Legacy Skill",
        )
        self.assertEqual(response.unavailable, {"mcp_server_ids": [], "skill_ids": []})

    def test_role_default_skills_update_writes_only_role_list(self) -> None:
        import yaml

        from cairn.server.routers.capabilities import update_role_default_skills
        from cairn.server.schemas import RoleDefaultSkillsUpdateRequest

        skill_dir = self.yaml.root / "role-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Role Skill\n", encoding="utf-8")
        data = yaml.safe_load(self.yaml.capabilities_path.read_text(encoding="utf-8"))
        data["capabilities"]["skills"] = [
            {
                "id": "role-skill",
                "name": "Role Skill",
                "source_path": str(skill_dir),
                "task_types": ["bootstrap"],
            },
            {
                "id": "other-skill",
                "name": "Other Skill",
                "source_path": str(skill_dir),
                "task_types": ["bootstrap"],
            },
        ]
        data["roles"] = [
            {
                "id": "role1",
                "name": "Role",
                "prompt": "prompt",
                "default_skill_ids": ["other-skill"],
                "task_types": ["bootstrap"],
            }
        ]
        self.yaml.capabilities_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        role = update_role_default_skills(
            "role1",
            RoleDefaultSkillsUpdateRequest(default_skill_ids=[" role-skill ", "role-skill", "", "other-skill"]),
        )

        after = yaml.safe_load(self.yaml.capabilities_path.read_text(encoding="utf-8"))
        self.assertEqual(role.default_skill_ids, ["role-skill", "other-skill"])
        self.assertEqual(after["roles"][0]["default_skill_ids"], ["role-skill", "other-skill"])
        self.assertEqual([item["id"] for item in after["capabilities"]["skills"]], ["role-skill", "other-skill"])
        self.assertTrue((skill_dir / "SKILL.md").exists())

        role = update_role_default_skills("role1", RoleDefaultSkillsUpdateRequest(default_skill_ids=["other-skill"]))
        after = yaml.safe_load(self.yaml.capabilities_path.read_text(encoding="utf-8"))
        self.assertEqual(role.default_skill_ids, ["other-skill"])
        self.assertEqual(after["capabilities"]["skills"][0]["id"], "role-skill")
        self.assertTrue((skill_dir / "SKILL.md").exists())

    def test_role_default_skills_rejects_unknown_skill_without_writing(self) -> None:
        import yaml
        from fastapi import HTTPException

        from cairn.server.routers.capabilities import update_role_default_skills
        from cairn.server.schemas import RoleDefaultSkillsUpdateRequest

        data = yaml.safe_load(self.yaml.capabilities_path.read_text(encoding="utf-8"))
        data["roles"] = [
            {
                "id": "role1",
                "name": "Role",
                "prompt": "prompt",
                "default_skill_ids": [],
                "task_types": ["bootstrap"],
            }
        ]
        self.yaml.capabilities_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        before = self.yaml.capabilities_path.read_text(encoding="utf-8")

        with self.assertRaises(HTTPException) as cm:
            update_role_default_skills("role1", RoleDefaultSkillsUpdateRequest(default_skill_ids=["missing-skill"]))

        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(self.yaml.capabilities_path.read_text(encoding="utf-8"), before)

    def test_role_default_skills_rejects_unknown_role_without_writing(self) -> None:
        import yaml
        from fastapi import HTTPException

        from cairn.server.routers.capabilities import update_role_default_skills
        from cairn.server.schemas import RoleDefaultSkillsUpdateRequest

        skill_dir = self.yaml.root / "role-skill"
        skill_dir.mkdir()
        data = yaml.safe_load(self.yaml.capabilities_path.read_text(encoding="utf-8"))
        data["capabilities"]["skills"] = [
            {
                "id": "role-skill",
                "name": "Role Skill",
                "source_path": str(skill_dir),
                "task_types": ["bootstrap"],
            }
        ]
        self.yaml.capabilities_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        before = self.yaml.capabilities_path.read_text(encoding="utf-8")

        with self.assertRaises(HTTPException) as cm:
            update_role_default_skills("missing-role", RoleDefaultSkillsUpdateRequest(default_skill_ids=["role-skill"]))

        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(self.yaml.capabilities_path.read_text(encoding="utf-8"), before)

    def test_role_default_skills_request_rejects_path_like_ids(self) -> None:
        from pydantic import ValidationError

        from cairn.server.schemas import RoleDefaultSkillsUpdateRequest

        for skill_id in ("bad skill", "bad/skill", "bad\\skill"):
            with self.subTest(skill_id=skill_id):
                with self.assertRaises(ValidationError):
                    RoleDefaultSkillsUpdateRequest(default_skill_ids=[skill_id])

    def test_probe_mcp_success_updates_yaml_status(self) -> None:
        from cairn.server.routers.capabilities import (
            get_capability_catalog,
            probe_admin_capability,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

        upsert_admin_capability("mcp_server", "stdio-mcp", CapabilityAdminRequest(
            id="stdio-mcp",
            name="Stdio MCP",
            task_types=["explore"],
            transport="stdio",
            command="/usr/local/bin/mcp-server",
        ))

        response = MagicMock()
        response.read.return_value = json.dumps({
            "results": [
                {"capability_id": "stdio-mcp", "status": "ok", "message": "initialize + tools/list ok"}
            ]
        }).encode("utf-8")
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            entry = probe_admin_capability("mcp_server", "stdio-mcp")

        self.assertEqual(entry.status, "ok")
        self.assertEqual(entry.message, "initialize + tools/list ok")
        items = {item.id: item for item in get_capability_catalog() if item.kind == "mcp_server"}
        self.assertTrue(items["stdio-mcp"].available)
        self.assertEqual(items["stdio-mcp"].last_probe_status, "ok")
        self.assertEqual(items["stdio-mcp"].last_probe_message, "initialize + tools/list ok")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:9100/mcp-probe")

    def test_probe_mcp_failure_updates_yaml_status(self) -> None:
        from cairn.server.routers.capabilities import (
            get_capability_catalog,
            probe_admin_capability,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

        upsert_admin_capability("mcp_server", "bad-mcp", CapabilityAdminRequest(
            id="bad-mcp",
            name="Bad MCP",
            task_types=["bootstrap"],
            transport="stdio",
            command="bad-mcp",
        ))

        response = MagicMock()
        response.read.return_value = json.dumps({
            "results": [
                {"capability_id": "bad-mcp", "status": "error", "message": "connection refused"}
            ]
        }).encode("utf-8")
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            entry = probe_admin_capability("mcp_server", "bad-mcp")

        self.assertEqual(entry.status, "error")
        self.assertEqual(entry.message, "connection refused")
        items = {item.id: item for item in get_capability_catalog() if item.kind == "mcp_server"}
        self.assertFalse(items["bad-mcp"].available)
        self.assertEqual(items["bad-mcp"].last_probe_status, "error")

    def test_probe_all_mcp_updates_each_result(self) -> None:
        from cairn.server.routers.capabilities import (
            get_capability_catalog,
            probe_all_admin_mcp_servers,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

        for capability_id in ("a-mcp", "b-mcp"):
            upsert_admin_capability("mcp_server", capability_id, CapabilityAdminRequest(
                id=capability_id,
                name=capability_id,
                task_types=["bootstrap"],
                transport="stdio",
                command=capability_id,
            ))

        response = MagicMock()
        response.read.return_value = json.dumps({
            "results": [
                {"capability_id": "a-mcp", "status": "ok", "message": "ready"},
                {"capability_id": "b-mcp", "status": "error", "message": "boom"},
            ]
        }).encode("utf-8")
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            results = probe_all_admin_mcp_servers()

        by_id = {item.capability_id: item for item in results}
        self.assertEqual(by_id["a-mcp"].status, "ok")
        self.assertEqual(by_id["b-mcp"].status, "error")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data.decode("utf-8"))["server_ids"], ["a-mcp", "b-mcp"])
        items = {item.id: item for item in get_capability_catalog() if item.kind == "mcp_server"}
        self.assertTrue(items["a-mcp"].available)
        self.assertFalse(items["b-mcp"].available)

    def test_dispatcher_unreachable_marks_target_error(self) -> None:
        from cairn.server.routers.capabilities import (
            get_capability_catalog,
            probe_admin_capability,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

        upsert_admin_capability("mcp_server", "offline-mcp", CapabilityAdminRequest(
            id="offline-mcp",
            name="Offline MCP",
            task_types=["bootstrap"],
            transport="stdio",
            command="offline-mcp",
        ))
        with patch("urllib.request.urlopen", side_effect=OSError("dispatcher down")):
            entry = probe_admin_capability("mcp_server", "offline-mcp")

        self.assertEqual(entry.status, "error")
        self.assertIn("dispatcher probe failed", entry.message)
        items = {item.id: item for item in get_capability_catalog() if item.kind == "mcp_server"}
        self.assertFalse(items["offline-mcp"].available)

    def test_skill_probe_remains_local(self) -> None:
        from cairn.server.routers.capabilities import probe_admin_capability, upsert_admin_capability
        from cairn.server.schemas import CapabilityAdminRequest

        skill_dir = self.yaml.root / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
        upsert_admin_capability("skill", "skill", CapabilityAdminRequest(
            id="skill",
            name="Skill",
            task_types=["bootstrap"],
            source_path=str(skill_dir),
        ))

        entry = probe_admin_capability("skill", "skill")
        self.assertEqual(entry.status, "ok")
        self.assertEqual(entry.message, "skill manifest readable")


class CapabilityAdminYamlMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.yaml = TempYamlConfig(resources={
            "capabilities": {
                "mcp_servers": [
                    {
                        "id": "builtin-mcp",
                        "name": "Builtin MCP",
                        "source": "builtin",
                        "task_types": ["bootstrap"],
                        "transport": "stdio",
                        "command": "builtin-mcp",
                    }
                ],
                "skills": [
                    {
                        "id": "builtin-skill",
                        "name": "Builtin Skill",
                        "source": "builtin",
                        "task_types": ["bootstrap"],
                        "source_path": "/tmp/builtin-skill",
                    }
                ],
            },
            "roles": [],
        })
        self.yaml.__enter__()

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def test_admin_delete_allows_builtin_capabilities(self) -> None:
        from cairn.server.routers.capabilities import delete_admin_capability, get_capability_catalog

        delete_admin_capability("mcp_server", "builtin-mcp")
        delete_admin_capability("skill", "builtin-skill")

        items = {(item.kind, item.id): item for item in get_capability_catalog()}
        self.assertNotIn(("mcp_server", "builtin-mcp"), items)
        self.assertNotIn(("skill", "builtin-skill"), items)


class DispatcherConfigRequiredSkillIdsTests(unittest.TestCase):
    def test_yaml_mcp_required_skill_must_resolve(self) -> None:
        from pydantic import ValidationError

        from cairn.shared.config import (
            CapabilitiesConfig,
            McpServerCapabilityConfig,
            SkillCapabilityConfig,
        )

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
        from pydantic import ValidationError

        from cairn.shared.config import CapabilitiesConfig, SkillCapabilityConfig

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
