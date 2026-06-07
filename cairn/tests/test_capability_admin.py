"""Tests for the capability catalog admin + per-task project snapshots."""
from __future__ import annotations

import os
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
            capabilities_per_task={
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
            ai_profile_selections=self._create_profile(),
        ))
        pid = created.project.id
        with self.db.get_conn() as conn:
            per_task = load_project_capabilities_per_task(conn, pid)
        self.assertEqual(per_task["bootstrap"].mcp_server_ids, ["m"])
        self.assertEqual(per_task["bootstrap"].skill_ids, ["s"])
        self.assertEqual(per_task["explore"].mcp_server_ids, ["m"])
        self.assertEqual(per_task["reason"].mcp_server_ids, [])

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
        skill = catalog[("skill", "builtin-skill")].item
        self.assertEqual(skill.source_path, "/opt/capabilities/skills/builtin-skill")

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


if __name__ == "__main__":
    unittest.main()
