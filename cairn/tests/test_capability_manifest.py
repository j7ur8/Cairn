from __future__ import annotations

import os
os.environ.setdefault('CAIRN_JWT_SECRET', 'test-jwt-secret-do-not-use-in-prod-32bytes')
os.environ.setdefault('CAIRN_SECRETS_KEY', 'test-jwt-secret-do-not-use-in-prod-32bytes')

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class CapabilityManifestTests(unittest.TestCase):
    def test_manifest_lists_selected_mcp_and_skills_without_secrets(self) -> None:
        from cairn.dispatcher.tasks.bootstrap import _capability_manifest_payload

        payload = _capability_manifest_payload(
            "proj_001",
            "bootstrap",
            {
                "selection": {
                    "mcp_server_ids": ["http-mcp", "kali"],
                    "skill_ids": ["cypher-ctf", "missing-skill"],
                },
                "catalog": [
                    {
                        "kind": "mcp_server",
                        "id": "http-mcp",
                        "name": "HTTP MCP",
                        "detail": "http",
                        "available": True,
                        "task_types": ["bootstrap", "explore"],
                        "headers": {"Authorization": "Bearer should-not-appear"},
                        "env": {"TOKEN": "should-not-appear"},
                    },
                    {
                        "kind": "mcp_server",
                        "id": "kali",
                        "name": "Kali",
                        "detail": "stdio",
                        "available": True,
                        "task_types": ["explore"],
                    },
                    {
                        "kind": "skill",
                        "id": "cypher-ctf",
                        "name": "Cypher CTF",
                        "detail": "directory",
                        "available": True,
                        "task_types": ["bootstrap"],
                    },
                ],
                "unavailable_mcp_server_ids": ["old-mcp"],
                "unavailable_skill_ids": ["missing-skill"],
            },
        )

        self.assertEqual(payload["summary"], "Project capabilities before bootstrap: 2 MCP servers, 2 skills")
        self.assertEqual(payload["project_id"], "proj_001")
        self.assertTrue(payload["mcp_servers"][0]["enabled_for_task"])
        self.assertFalse(payload["mcp_servers"][1]["enabled_for_task"])
        self.assertTrue(payload["skills"][0]["enabled_for_task"])
        self.assertFalse(payload["skills"][1]["available"])
        self.assertEqual(payload["unavailable_mcp_server_ids"], ["old-mcp"])
        self.assertEqual(payload["unavailable_skill_ids"], ["missing-skill"])
        rendered = repr(payload)
        self.assertNotIn("should-not-appear", rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("TOKEN", rendered)

    def test_manifest_empty_when_selection_unavailable(self) -> None:
        from cairn.dispatcher.tasks.bootstrap import _capability_manifest_payload

        payload = _capability_manifest_payload("proj_002", "bootstrap", None)

        self.assertEqual(payload["mcp_servers"], [])
        self.assertEqual(payload["skills"], [])
        self.assertIn("no capability selection available", payload["summary"])

    def test_dispatcher_catalog_payload_carries_probe_fields(self) -> None:
        from cairn.dispatcher.capabilities import catalog_payload
        from cairn.dispatcher.config import (
            McpServerCapabilityConfig, SkillCapabilityConfig,
        )
        config = SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="kali-server-mcp",
                        name="Kali",
                        command="/usr/local/bin/kali-mcp-stdio",
                        args=["--stdio"],
                        task_types=["explore"],
                    )
                ],
                skills=[
                    SkillCapabilityConfig(
                        id="cypher-ctf",
                        name="Cypher CTF",
                        source_path="/cairn/capabilities/skills/cypher-ctf",
                        task_types=["explore"],
                    )
                ],
            )
        )

        payload = catalog_payload(config)
        mcp = next(item for item in payload if item["kind"] == "mcp_server")
        skill = next(item for item in payload if item["kind"] == "skill")
        self.assertEqual(mcp["transport"], "stdio")
        self.assertEqual(mcp["command"], "/usr/local/bin/kali-mcp-stdio")
        self.assertEqual(mcp["args"], ["--stdio"])
        self.assertIn("source_path", mcp)
        self.assertEqual(skill["source_path"], "/cairn/capabilities/skills/cypher-ctf")


if __name__ == "__main__":
    unittest.main()
