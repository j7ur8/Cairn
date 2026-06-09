"""Tests for the capability catalog admin + per-task project snapshots."""
from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


def _fresh_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    return Path(tmp.name)


class CapabilityAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _fresh_db()
        from cairn.server import db
        db._db_path = None
        db.close_thread_conn()
        db.configure(self.tmp)
        self.db = db

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db._db_path = None
        os.unlink(self.tmp)

    def _create_project(self) -> str:
        from cairn.server.routers.projects import next_project_id
        with self.db.get_conn() as conn:
            pid = next_project_id(conn)
            now = "2026-06-08T00:00:00Z"
            conn.execute(
                "INSERT INTO projects (id, title, status, created_at) VALUES (?, ?, 'active', ?)",
                (pid, "p", now),
            )
            conn.execute(
                "INSERT INTO facts (id, project_id, description) VALUES ('origin', ?, 'o')",
                (pid,),
            )
            conn.execute(
                "INSERT INTO facts (id, project_id, description) VALUES ('goal', ?, 'g')",
                (pid,),
            )
        return pid

    def _create_profile(self):
        from cairn.server.models import (
            AiProfileCreate, AiProfileSelection, TaskAiProfileSelections,
        )
        from cairn.server.routers.ai_profiles import create_ai_profile
        p = create_ai_profile(AiProfileCreate(
            name="t", worker_type="codex", model="m", api_key_env="K",
        ))
        sel = AiProfileSelection(
            primary_profile_id=p.id,
            primary_model="m",
            primary_reasoning_type="medium",
        )
        return TaskAiProfileSelections(
            bootstrap=sel, explore=sel, reason=sel,
        )

    def test_admin_upsert_and_delete(self) -> None:
        from cairn.server.capabilities_service import (
            delete_user_capability, get_catalog_map, list_catalog,
            upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="my-mcp", name="My MCP", task_types=["bootstrap", "explore"],
                transport="stdio", source_path="/tmp/mcp",
            ))
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="my-skill", name="My Skill", task_types=["bootstrap"],
                source_path="/tmp/skill",
            ))
            items = {item.id: item for item in list_catalog(conn)}
            self.assertEqual(items["my-mcp"].source, "user")
            self.assertEqual(items["my-skill"].source, "user")
            delete_user_capability(conn, "skill", "my-skill")
            catalog = get_catalog_map(conn)
            self.assertIn(("mcp_server", "my-mcp"), catalog)
            self.assertNotIn(("skill", "my-skill"), catalog)

    def test_skill_requires_cycle_rejected(self) -> None:
        from cairn.server.capabilities_service import upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        from fastapi import HTTPException
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="b", name="B", task_types=["bootstrap"],
                source_path="/tmp/b",
            ))
            # Now a -> b is fine.
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"], requires_ids=["b"],
                source_path="/tmp/a",
            ))
            # Closing the cycle b -> a must fail.
            with self.assertRaises(HTTPException) as ctx:
                upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                    id="b", name="B", task_types=["bootstrap"], requires_ids=["a"],
                    source_path="/tmp/b",
                ))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("cycle", str(ctx.exception.detail))

    def test_requires_self_reference_rejected(self) -> None:
        from cairn.server.capabilities_service import upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        from fastapi import HTTPException
        with self.db.get_conn() as conn:
            with self.assertRaises(HTTPException):
                upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                    id="a", name="A", task_types=["bootstrap"],
                    requires_ids=["a"], source_path="/tmp/a",
                ))

    def test_mcp_server_requires_rejected(self) -> None:
        from cairn.server.capabilities_service import upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        from fastapi import HTTPException
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            with self.assertRaises(HTTPException):
                upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                    id="b", name="B", task_types=["bootstrap"],
                    requires_ids=["a"], transport="stdio", source_path="/tmp/b",
                ))

    def test_per_task_create_persists_snapshots(self) -> None:
        from cairn.server.capabilities_service import (
            get_catalog_map, load_project_capabilities_per_task,
            upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest, CreateProjectRequest
        from cairn.server.routers.projects import create_project
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="m", name="M", task_types=["bootstrap", "explore", "reason"],
                transport="stdio", source_path="/tmp/m",
            ))
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="s", name="S", task_types=["bootstrap"],
                source_path="/tmp/s",
            ))
        created = create_project(CreateProjectRequest(
            title="p", origin="o", goal="g",
            capabilities={
                "bootstrap": {
                    "mcp_server_ids": ["m"],
                    "skill_ids": ["s"],
                    "user_mcp_server_ids": ["m"],
                    "user_skill_ids": ["s"],
                },
                "explore": {
                    "mcp_server_ids": ["m"],
                    "skill_ids": [],
                    "user_mcp_server_ids": ["m"],
                    "user_skill_ids": [],
                },
                "reason": {
                    "mcp_server_ids": [],
                    "skill_ids": [],
                    "user_mcp_server_ids": [],
                    "user_skill_ids": [],
                },
            },
            ai_profiles=self._create_profile(),
        ))
        pid = created.project.id
        with self.db.get_conn() as conn:
            per_task = load_project_capabilities_per_task(conn, pid)
        self.assertEqual(per_task["bootstrap"].mcp_server_ids, ["m"])
        self.assertEqual(per_task["bootstrap"].skill_ids, ["s"])
        self.assertEqual(per_task["explore"].mcp_server_ids, ["m"])
        self.assertEqual(per_task["reason"].mcp_server_ids, [])

    def test_create_project_persists_llm_visible_event_config(self) -> None:
        import json
        from cairn.server.models import CreateProjectRequest
        from cairn.server.routers.projects import create_project

        project = create_project(CreateProjectRequest(
            title="p",
            origin="o",
            goal="g",
            llm_visible_event_kinds=["prompt", "agent_message"],
            ai_profiles=self._create_profile(),
        ))

        self.assertEqual(project.project.llm_visible_event_kinds, ["prompt", "agent_message"])

    def test_create_project_role_default_skill_snapshot(self) -> None:
        from cairn.server.capabilities_service import (
            expand_task_capabilities,
            get_catalog_map,
            load_project_capabilities_per_task,
            persist_project_capabilities_per_task,
            upsert_user_capability,
        )
        from cairn.server.models import (
            CapabilityAdminRequest, CreateProjectRequest,
            RegisterRoleCatalogItem, RegisterRoleCatalogRequest,
        )
        from cairn.server.routers.capabilities import register_role_catalog
        from cairn.server.routers.projects import create_project

        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="role-skill", name="Role Skill", task_types=["bootstrap", "explore"],
                source_path="/tmp/role-skill",
            ))
        register_role_catalog(RegisterRoleCatalogRequest(roles=[
            RegisterRoleCatalogItem(
                id="role1", name="Role", prompt="prompt",
                default_skill_ids=["role-skill"],
            ),
        ]))

        project = create_project(CreateProjectRequest(
            title="p", origin="o", goal="g",
            role_id="role1",
            ai_profiles=self._create_profile(),
        ))

        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT task_type, source FROM project_capability_snapshots
                WHERE project_id = ? AND kind = 'skill' AND capability_id = 'role-skill'
                ORDER BY task_type
                """,
                (project.project.id,),
            ).fetchall()
            per_task = load_project_capabilities_per_task(conn, project.project.id)

        self.assertEqual(
            [(row["task_type"], row["source"]) for row in rows],
            [("bootstrap", "role_default"), ("explore", "role_default")],
        )
        self.assertEqual(per_task["bootstrap"].skill_ids, ["role-skill"])
        self.assertEqual(per_task["bootstrap"].role_default_skill_ids, ["role-skill"])
        self.assertEqual(per_task["bootstrap"].user_skill_ids, [])
        with self.db.get_conn() as conn:
            catalog = get_catalog_map(conn)
            expanded, _ = expand_task_capabilities(per_task, catalog)
            persist_project_capabilities_per_task(conn, project.project.id, expanded, "2026-06-09T00:00:00Z")
            row = conn.execute(
                """
                SELECT source FROM project_capability_snapshots
                WHERE project_id = ? AND task_type = 'bootstrap'
                  AND kind = 'skill' AND capability_id = 'role-skill'
                """,
                (project.project.id,),
            ).fetchone()
        self.assertEqual(row["source"], "role_default")
        self.assertIn("usage", project.project.llm_hidden_event_kinds)
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT llm_hidden_event_kinds FROM projects WHERE id = ?",
                (project.project.id,),
            ).fetchone()
        hidden = json.loads(row["llm_hidden_event_kinds"])
        self.assertNotIn("prompt", hidden)
        self.assertNotIn("agent_message", hidden)
        self.assertIn("usage", hidden)

    def test_requires_auto_expands_in_same_task(self) -> None:
        from cairn.server.capabilities_service import (
            expand_task_capabilities, get_catalog_map,
            upsert_user_capability,
        )
        from cairn.server.models import (
            CapabilityAdminRequest, TaskCapabilities,
        )
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="child", name="C", task_types=["bootstrap"],
                source_path="/tmp/c",
            ))
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="parent", name="P", task_types=["bootstrap"],
                requires_ids=["child"], source_path="/tmp/p",
            ))
        with self.db.get_conn() as conn:
            catalog = get_catalog_map(conn)
            per_task = {
                "bootstrap": TaskCapabilities(
                    mcp_server_ids=[], skill_ids=["parent"],
                    user_mcp_server_ids=[], user_skill_ids=["parent"],
                ),
                "explore": TaskCapabilities(),
                "reason": TaskCapabilities(),
            }
            expanded, _errors = expand_task_capabilities(per_task, catalog)
        self.assertIn("parent", expanded["bootstrap"].skill_ids)
        self.assertIn("child", expanded["bootstrap"].skill_ids)
        self.assertNotIn("child", expanded["bootstrap"].user_skill_ids)
        self.assertEqual(expanded["explore"].skill_ids, [])

    def test_probe_records_status(self) -> None:
        from cairn.server.capabilities_service import (
            probe_capability, upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="probe-skill", name="P", task_types=["bootstrap"],
                source_path="/this/path/does/not/exist",
            ))
        with self.db.get_conn() as conn:
            entry = probe_capability(conn, "skill", "probe-skill")
        self.assertEqual(entry.status, "error")

    def test_probe_stdio_command_without_source_path_is_not_false_warning(self) -> None:
        from cairn.server.capabilities_service import (
            probe_capability, upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="stdio-mcp", name="Stdio MCP", task_types=["explore"],
                transport="stdio", command="/usr/local/bin/mcp-server",
            ))
        with self.db.get_conn() as conn:
            entry = probe_capability(conn, "mcp_server", "stdio-mcp")
        self.assertEqual(entry.status, "ok")
        self.assertEqual(entry.message, "stdio command configured")

    def test_register_builtin_catalog_persists_probe_fields(self) -> None:
        from cairn.server.capabilities_service import (
            get_catalog_map, register_builtin_catalog,
        )
        with self.db.get_conn() as conn:
            register_builtin_catalog(conn, [
                {
                    "kind": "mcp_server",
                    "id": "builtin-mcp",
                    "name": "Builtin MCP",
                    "description": "desc",
                    "task_types": ["explore"],
                    "available": True,
                    "detail": "stdio",
                    "transport": "stdio",
                    "command": "/usr/local/bin/builtin-mcp",
                    "args": ["--stdio"],
                    "source_path": "/opt/capabilities/mcp",
                    "probe_config": {
                        "type": "chrome_devtools_http",
                        "url": "http://host.docker.internal:9222/json/version",
                    },
                    "use_when": ["browser evidence is needed"],
                    "activation_hint": "Use for browser runtime inspection.",
                },
                {
                    "kind": "skill",
                    "id": "builtin-skill",
                    "name": "Builtin Skill",
                    "description": "desc",
                    "task_types": ["explore"],
                    "available": True,
                    "detail": "directory",
                    "source_path": "/opt/capabilities/skills/builtin-skill",
                    "use_when": ["reverse workflow is needed"],
                    "preferred_mcp_ids": ["builtin-mcp"],
                    "activation_hint": "Read SKILL.md first.",
                },
            ])
            catalog = get_catalog_map(conn)
        mcp = catalog[("mcp_server", "builtin-mcp")].item
        self.assertEqual(mcp.transport, "stdio")
        self.assertEqual(mcp.command, "/usr/local/bin/builtin-mcp")
        self.assertEqual(mcp.args, ["--stdio"])
        self.assertEqual(mcp.source_path, "/opt/capabilities/mcp")
        self.assertEqual(
            mcp.probe_config,
            {"type": "chrome_devtools_http", "url": "http://host.docker.internal:9222/json/version"},
        )
        self.assertEqual(mcp.use_when, ["browser evidence is needed"])
        self.assertEqual(mcp.activation_hint, "Use for browser runtime inspection.")
        skill = catalog[("skill", "builtin-skill")].item
        self.assertEqual(skill.source_path, "/opt/capabilities/skills/builtin-skill")
        self.assertEqual(skill.use_when, ["reverse workflow is needed"])
        self.assertEqual(skill.preferred_mcp_ids, ["builtin-mcp"])
        self.assertEqual(skill.activation_hint, "Read SKILL.md first.")

    def test_probe_chrome_devtools_http_reports_reachable(self) -> None:
        from cairn.server.capabilities_service import (
            probe_capability, register_builtin_catalog,
        )
        from unittest.mock import MagicMock, patch
        with self.db.get_conn() as conn:
            register_builtin_catalog(conn, [
                {
                    "kind": "mcp_server",
                    "id": "chrome-devtools-host",
                    "name": "Host Chrome",
                    "description": "desc",
                    "task_types": ["bootstrap"],
                    "available": True,
                    "detail": "stdio",
                    "transport": "stdio",
                    "command": "chrome-devtools-mcp",
                    "args": ["--browserUrl=http://host.docker.internal:9222"],
                    "probe_config": {
                        "type": "chrome_devtools_http",
                        "url": "http://host.docker.internal:9222/json/version",
                    },
                },
            ])
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/browser/abc"}'
        with patch("socket.gethostbyname", return_value="0.250.250.254"), patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            with self.db.get_conn() as conn:
                entry = probe_capability(conn, "mcp_server", "chrome-devtools-host")
        self.assertEqual(entry.status, "ok")
        self.assertEqual(entry.message, "chrome devtools endpoint reachable")
        self.assertEqual(
            mock_urlopen.call_args.args[0],
            "http://0.250.250.254:9222/json/version",
        )


    def test_admin_catalog_includes_admin_fields(self) -> None:
        from cairn.server.capabilities_service import (
            get_catalog_map, upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="fetch-mcp", name="Fetch", task_types=["bootstrap"],
                transport="stdio", source_path="/tmp/fetch",
                command="python", args=["-m", "fetch_server"],
            ))
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="summarize", name="Summarize", task_types=["reason"],
                source_path="/tmp/summarize",
            ))
        with self.db.get_conn() as conn:
            catalog = get_catalog_map(conn)
        mcp = catalog[("mcp_server", "fetch-mcp")].item
        self.assertEqual(mcp.source_path, "/tmp/fetch")
        self.assertEqual(mcp.transport, "stdio")
        self.assertEqual(mcp.command, "python")
        self.assertEqual(mcp.args, ["-m", "fetch_server"])
        skill = catalog[("skill", "summarize")].item
        self.assertEqual(skill.source_path, "/tmp/summarize")

    def test_admin_routing_metadata_round_trips(self) -> None:
        from cairn.server.capabilities_service import get_catalog_map, upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="browser", name="Browser", task_types=["bootstrap"],
                transport="stdio", source_path="/tmp/browser", command="browser",
                use_when=["browser runtime inspection is needed"],
                activation_hint="Use for runtime evidence.",
            ))
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="reverse-js", name="Reverse JS", task_types=["bootstrap"],
                source_path="/tmp/reverse-js",
                use_when=["sign tokens must be traced"],
                preferred_mcp_ids=["browser"],
                activation_hint="Read SKILL.md first.",
            ))
            catalog = get_catalog_map(conn)
        mcp = catalog[("mcp_server", "browser")].item
        skill = catalog[("skill", "reverse-js")].item
        self.assertEqual(mcp.use_when, ["browser runtime inspection is needed"])
        self.assertEqual(mcp.activation_hint, "Use for runtime evidence.")
        self.assertEqual(skill.use_when, ["sign tokens must be traced"])
        self.assertEqual(skill.preferred_mcp_ids, ["browser"])
        self.assertEqual(skill.activation_hint, "Read SKILL.md first.")

    def test_admin_skill_preferred_mcp_rejects_unknown_id(self) -> None:
        from cairn.server.capabilities_service import upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        from fastapi import HTTPException
        with self.db.get_conn() as conn:
            with self.assertRaises(HTTPException) as ctx:
                upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                    id="reverse-js", name="Reverse JS", task_types=["bootstrap"],
                    source_path="/tmp/reverse-js",
                    preferred_mcp_ids=["missing-mcp"],
                ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("missing-mcp", str(ctx.exception.detail))

    def test_admin_mcp_server_preferred_mcp_rejected(self) -> None:
        from cairn.server.capabilities_service import upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        from fastapi import HTTPException
        with self.db.get_conn() as conn:
            with self.assertRaises(HTTPException):
                upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                    id="m", name="M", task_types=["bootstrap"],
                    transport="stdio", source_path="/tmp/m", command="m",
                    preferred_mcp_ids=["other-mcp"],
                ))


class McpRequiredSkillIdsTests(unittest.TestCase):
    """MCP -> required_skill_ids binding.

    Mirrors the existing skill.requires_ids semantics: an MCP row can
    declare a list of skill ids; the per-task expansion layer will
    auto-inject those skills (with source="required") whenever the MCP
    is selected.
    """

    def setUp(self) -> None:
        self.tmp = _fresh_db()
        from cairn.server import db
        db._db_path = None
        db.close_thread_conn()
        db.configure(self.tmp)
        self.db = db

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db._db_path = None
        os.unlink(self.tmp)

    # -- admin write path --

    def test_admin_mcp_required_skill_ids_rejects_unknown_id(self) -> None:
        from cairn.server.capabilities_service import upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        from fastapi import HTTPException
        with self.db.get_conn() as conn:
            with self.assertRaises(HTTPException) as ctx:
                upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                    id="x", name="X", task_types=["bootstrap"],
                    transport="stdio", source_path="/tmp/x", command="x",
                    required_skill_ids=["ghost-skill"],
                ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("ghost-skill", str(ctx.exception.detail))

    def test_admin_mcp_required_skill_ids_accepts_known_id(self) -> None:
        from cairn.server.capabilities_service import (
            get_catalog_map, upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="m", name="M", task_types=["bootstrap"],
                transport="stdio", source_path="/tmp/m", command="m",
                required_skill_ids=["a"],
            ))
            catalog = get_catalog_map(conn)
        self.assertEqual(catalog[("mcp_server", "m")].item.required_skill_ids, ["a"])

    def test_admin_skill_required_skill_ids_rejected(self) -> None:
        from cairn.server.capabilities_service import upsert_user_capability
        from cairn.server.models import CapabilityAdminRequest
        from fastapi import HTTPException
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            with self.assertRaises(HTTPException):
                upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                    id="b", name="B", task_types=["bootstrap"],
                    source_path="/tmp/b",
                    required_skill_ids=["a"],
                ))

    # -- expansion path --

    def test_expansion_auto_adds_required_skill(self) -> None:
        from cairn.server.capabilities_service import (
            expand_task_capabilities, get_catalog_map,
            upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest, TaskCapabilities, task_capabilities_map
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap", "explore"],
                source_path="/tmp/a",
            ))
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="m", name="M", task_types=["bootstrap", "explore"],
                transport="stdio", source_path="/tmp/m", command="m",
                required_skill_ids=["a"],
            ))
        per_task = task_capabilities_map({
            "bootstrap": {
                "mcp_server_ids": ["m"],
                "user_mcp_server_ids": ["m"],
            },
        })
        with self.db.get_conn() as conn:
            catalog = get_catalog_map(conn)
            expanded, _ = expand_task_capabilities(per_task, catalog)
        self.assertEqual(expanded["bootstrap"].mcp_server_ids, ["m"])
        self.assertEqual(expanded["bootstrap"].skill_ids, ["a"])
        self.assertEqual(expanded["bootstrap"].user_skill_ids, [])

    def test_expansion_does_not_duplicate_when_user_already_picked(self) -> None:
        from cairn.server.capabilities_service import (
            expand_task_capabilities, get_catalog_map,
            upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest, task_capabilities_map
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="m", name="M", task_types=["bootstrap"],
                transport="stdio", source_path="/tmp/m", command="m",
                required_skill_ids=["a"],
            ))
        per_task = task_capabilities_map({
            "bootstrap": {
                "mcp_server_ids": ["m"],
                "skill_ids": ["a"],
                "user_mcp_server_ids": ["m"],
                "user_skill_ids": ["a"],
            },
        })
        with self.db.get_conn() as conn:
            catalog = get_catalog_map(conn)
            expanded, _ = expand_task_capabilities(per_task, catalog)
        self.assertEqual(expanded["bootstrap"].skill_ids, ["a"])
        self.assertEqual(expanded["bootstrap"].user_skill_ids, ["a"])

    def test_expansion_respects_task_type_gating(self) -> None:
        """Required skill only enabled for ``bootstrap`` is silently
        dropped on ``explore``, matching the existing skill->skill
        sub-skill walk. No error is emitted; the user did not pick the
        skill directly so a missing auto-required dependency is a
        silent no-op, not a failure.
        """
        from cairn.server.capabilities_service import (
            expand_task_capabilities, get_catalog_map,
            upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest, task_capabilities_map
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="m", name="M", task_types=["bootstrap", "explore"],
                transport="stdio", source_path="/tmp/m", command="m",
                required_skill_ids=["a"],
            ))
        per_task = task_capabilities_map({
            "bootstrap": {
                "mcp_server_ids": ["m"],
                "user_mcp_server_ids": ["m"],
            },
            "explore": {
                "mcp_server_ids": ["m"],
                "user_mcp_server_ids": ["m"],
            },
        })
        with self.db.get_conn() as conn:
            catalog = get_catalog_map(conn)
            expanded, _ = expand_task_capabilities(per_task, catalog)
        self.assertEqual(expanded["bootstrap"].skill_ids, ["a"])
        self.assertEqual(expanded["explore"].skill_ids, [])

    def test_persistence_snapshot_marks_required_source(self) -> None:
        from cairn.server.capabilities_service import (
            upsert_user_capability,
        )
        from cairn.server.models import (
            AiProfileCreate, AiProfileSelection, CapabilityAdminRequest,
            CreateProjectRequest, TaskAiProfileSelections,
        )
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.routers.projects import create_project
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            upsert_user_capability(conn, "mcp_server", CapabilityAdminRequest(
                id="m", name="M", task_types=["bootstrap"],
                transport="stdio", source_path="/tmp/m", command="m",
                required_skill_ids=["a"],
            ))
        profile = create_ai_profile(AiProfileCreate(
            name="t", worker_type="codex", model="m", api_key_env="K",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="m",
            primary_reasoning_type="medium",
        )
        project = create_project(CreateProjectRequest(
            title="p", origin="o", goal="g",
            capabilities={
                "bootstrap": {
                    "mcp_server_ids": ["m"],
                    "user_mcp_server_ids": ["m"],
                },
                "explore": {"mcp_server_ids": [], "user_mcp_server_ids": []},
                "reason": {"mcp_server_ids": [], "user_mcp_server_ids": []},
            },
            ai_profiles=TaskAiProfileSelections(
                bootstrap=selection, explore=selection, reason=selection,
            ),
        ))
        with self.db.get_conn() as conn:
            row = conn.execute(
                """
                SELECT source FROM project_capability_snapshots
                WHERE project_id = ? AND task_type = 'bootstrap'
                  AND kind = 'skill' AND capability_id = 'a'
                """,
                (project.project.id,),
            ).fetchone()
        self.assertEqual(row["source"], "required")

    def test_register_builtin_catalog_persists_required_skill_ids(self) -> None:
        from cairn.server.capabilities_service import (
            get_catalog_map, register_builtin_catalog, upsert_user_capability,
        )
        from cairn.server.models import CapabilityAdminRequest
        with self.db.get_conn() as conn:
            upsert_user_capability(conn, "skill", CapabilityAdminRequest(
                id="a", name="A", task_types=["bootstrap"],
                source_path="/tmp/a",
            ))
            register_builtin_catalog(conn, [
                {
                    "kind": "mcp_server",
                    "id": "m",
                    "name": "M",
                    "task_types": ["bootstrap"],
                    "transport": "stdio",
                    "command": "m",
                    "required_skill_ids": ["a"],
                },
            ])
            catalog = get_catalog_map(conn)
        self.assertEqual(catalog[("mcp_server", "m")].item.required_skill_ids, ["a"])

    def test_migration_adds_column_with_default(self) -> None:
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT required_skill_ids FROM capability_catalog LIMIT 1"
            ).fetchone()
        # Pre-populated rows have the default '[]' from the ALTER; the
        # empty catalog returns no row, so just assert the column
        # exists in the schema.
        with self.db.get_conn() as conn:
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(capability_catalog)").fetchall()
            }
            role_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(role_catalog)").fetchall()
            }
        self.assertIn("required_skill_ids", cols)
        self.assertIn("use_when", cols)
        self.assertIn("activation_hint", cols)
        self.assertIn("preferred_mcp_ids", cols)
        self.assertIn("default_skill_ids", role_cols)

    def test_role_catalog_persists_default_skill_ids(self) -> None:
        from cairn.server.models import RegisterRoleCatalogItem, RegisterRoleCatalogRequest
        from cairn.server.routers.capabilities import register_role_catalog

        items = register_role_catalog(RegisterRoleCatalogRequest(roles=[
            RegisterRoleCatalogItem(
                id="role1", name="Role", prompt="prompt",
                default_skill_ids=["skill-a"],
            ),
        ]))

        self.assertEqual(items[0].default_skill_ids, ["skill-a"])
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT default_skill_ids FROM role_catalog WHERE id = 'role1'"
            ).fetchone()
        self.assertEqual(row["default_skill_ids"], '["skill-a"]')


class DispatcherConfigRequiredSkillIdsTests(unittest.TestCase):
    """dispatch.yaml validation rejects broken MCP -> skill bindings."""

    def test_yaml_mcp_required_skill_must_resolve(self) -> None:
        from cairn.dispatcher.config import (
            CapabilitiesConfig, McpServerCapabilityConfig, SkillCapabilityConfig,
        )
        from pydantic import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            CapabilitiesConfig(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="m", name="M", command="m",
                        required_skill_ids=["ghost"],
                    ),
                ],
                skills=[
                    SkillCapabilityConfig(
                        id="a", name="A", source_path="/tmp/a",
                    ),
                ],
            )
        self.assertIn("ghost", str(ctx.exception))

    def test_yaml_mcp_required_skill_resolves(self) -> None:
        from cairn.dispatcher.config import (
            CapabilitiesConfig, McpServerCapabilityConfig, SkillCapabilityConfig,
        )
        cfg = CapabilitiesConfig(
            mcp_servers=[
                McpServerCapabilityConfig(
                    id="m", name="M", command="m",
                    required_skill_ids=["a"],
                ),
            ],
            skills=[
                SkillCapabilityConfig(
                    id="a", name="A", source_path="/tmp/a",
                ),
            ],
        )
        self.assertEqual(cfg.mcp_servers[0].required_skill_ids, ["a"])

    def test_yaml_skill_preferred_mcp_must_resolve(self) -> None:
        from cairn.dispatcher.config import (
            CapabilitiesConfig, SkillCapabilityConfig,
        )
        from pydantic import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            CapabilitiesConfig(
                skills=[
                    SkillCapabilityConfig(
                        id="a", name="A", source_path="/tmp/a",
                        preferred_mcp_ids=["ghost-mcp"],
                    ),
                ],
            )
        self.assertIn("ghost-mcp", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
