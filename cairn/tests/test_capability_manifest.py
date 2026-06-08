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

    def test_dispatcher_catalog_payload_carries_probe_and_routing_fields(self) -> None:
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
                        probe_config={"type": "chrome_devtools_http", "url": "http://host.docker.internal:9222/json/version"},
                        required_skill_ids=["js-reverse"],
                        use_when=["browser runtime evidence is needed"],
                        activation_hint="Use for live browser inspection.",
                        task_types=["explore"],
                    )
                ],
                skills=[
                    SkillCapabilityConfig(
                        id="cypher-ctf",
                        name="Cypher CTF",
                        source_path="/cairn/capabilities/skills/cypher-ctf",
                        use_when=["ctf triage is needed"],
                        preferred_mcp_ids=["kali-server-mcp"],
                        activation_hint="Read SKILL.md first.",
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
        self.assertEqual(
            mcp["probe_config"],
            {"type": "chrome_devtools_http", "url": "http://host.docker.internal:9222/json/version"},
        )
        self.assertEqual(mcp["required_skill_ids"], ["js-reverse"])
        self.assertEqual(mcp["use_when"], ["browser runtime evidence is needed"])
        self.assertEqual(mcp["activation_hint"], "Use for live browser inspection.")
        self.assertEqual(mcp["preferred_mcp_ids"], [])
        self.assertIn("source_path", mcp)
        self.assertEqual(skill["source_path"], "/cairn/capabilities/skills/cypher-ctf")
        self.assertEqual(skill["use_when"], ["ctf triage is needed"])
        self.assertEqual(skill["preferred_mcp_ids"], ["kali-server-mcp"])
        self.assertEqual(skill["activation_hint"], "Read SKILL.md first.")


class DispatcherCatalogPayloadRequiredSkillIdsTests(unittest.TestCase):
    """catalog_payload carries required_skill_ids for MCP entries."""

    def test_payload_includes_required_skill_ids(self) -> None:
        from cairn.dispatcher.capabilities import catalog_payload
        from cairn.dispatcher.config import (
            McpServerCapabilityConfig, SkillCapabilityConfig,
        )
        from types import SimpleNamespace
        config = SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="camoufox-reverse",
                        name="Camoufox",
                        command="camoufox-reverse-mcp",
                        args=["--stdio"],
                        required_skill_ids=["cypher-js-reverse"],
                        task_types=["explore"],
                    ),
                ],
                skills=[
                    SkillCapabilityConfig(
                        id="cypher-js-reverse",
                        name="JS Reverse",
                        source_path="/cairn/capabilities/skills/cypher-js-reverse",
                        task_types=["explore"],
                    ),
                ],
            ),
        )
        payload = catalog_payload(config)
        mcp = next(item for item in payload if item["id"] == "camoufox-reverse")
        self.assertEqual(mcp["required_skill_ids"], ["cypher-js-reverse"])


class CapabilityInstructionRenderingTests(unittest.TestCase):
    def test_execute_instructions_render_dynamic_routing_metadata(self) -> None:
        from cairn.dispatcher.capabilities import _instructions
        from cairn.dispatcher.config import McpServerCapabilityConfig, SkillCapabilityConfig

        text = _instructions(
            "/tmp/cap/mcp.json",
            "/tmp/cap/skills",
            [
                McpServerCapabilityConfig(
                    id="chrome-devtools-host",
                    name="Host Chrome DevTools MCP",
                    command="chrome-devtools-mcp",
                    args=["--browserUrl=http://host.docker.internal:9222"],
                    required_skill_ids=["js-reverse-automation"],
                    use_when=["Browser runtime inspection is required."],
                    activation_hint="Use this MCP for runtime evidence.",
                )
            ],
            [
                SkillCapabilityConfig(
                    id="js-reverse-automation",
                    name="JS Reverse",
                    source_path="/repo/capabilities/skills/js-reverse-automation",
                    use_when=["sign, enc, token, or nonce generation must be traced."],
                    preferred_mcp_ids=["chrome-devtools-host"],
                    activation_hint="Read SKILL.md before using the paired browser MCP.",
                )
            ],
        )

        self.assertIn("Config file: /tmp/cap/mcp.json", text)
        self.assertIn("Use when", text)
        self.assertIn("Browser runtime inspection is required.", text)
        self.assertIn("Required skills", text)
        self.assertIn("js-reverse-automation", text)
        self.assertIn("Preferred MCP servers", text)
        self.assertIn("chrome-devtools-host", text)
        self.assertIn("/tmp/cap/skills/js-reverse-automation", text)
        self.assertIn("Read SKILL.md before using the paired browser MCP.", text)

    def test_reason_instructions_render_metadata_without_paths(self) -> None:
        from cairn.dispatcher.capabilities import _reason_instructions
        from cairn.dispatcher.config import McpServerCapabilityConfig, SkillCapabilityConfig

        text = _reason_instructions(
            [
                McpServerCapabilityConfig(
                    id="chrome-devtools-host",
                    name="Host Chrome DevTools MCP",
                    command="chrome-devtools-mcp",
                    required_skill_ids=["js-reverse-automation"],
                    use_when=["Browser runtime inspection is required."],
                    activation_hint="Use this MCP for runtime evidence.",
                )
            ],
            [
                SkillCapabilityConfig(
                    id="js-reverse-automation",
                    name="JS Reverse",
                    source_path="/repo/capabilities/skills/js-reverse-automation",
                    use_when=["Browser-side JavaScript reverse engineering is needed."],
                    preferred_mcp_ids=["chrome-devtools-host"],
                    activation_hint="Read SKILL.md before using the paired browser MCP.",
                )
            ],
        )

        self.assertIn("Do not execute tools", text)
        self.assertIn("Browser runtime inspection is required.", text)
        self.assertIn("Browser-side JavaScript reverse engineering is needed.", text)
        self.assertIn("Preferred MCP servers", text)
        self.assertNotIn("/repo/capabilities", text)
        self.assertNotIn("/tmp/cap", text)


if __name__ == "__main__":
    unittest.main()
