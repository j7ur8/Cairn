from __future__ import annotations

import os
import tempfile

os.environ.setdefault('CAIRN_JWT_SECRET', 'test-jwt-secret-do-not-use-in-prod-32bytes')
os.environ.setdefault('CAIRN_SECRETS_KEY', 'test-jwt-secret-do-not-use-in-prod-32bytes')

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class CapabilityManifestTests(unittest.TestCase):
    def test_manifest_lists_selected_mcp_and_skills_without_secrets(self) -> None:
        from cairn.shared.capability_projection import capability_manifest_payload

        payload = capability_manifest_payload(
            "proj_001",
            "bootstrap",
            {
                "tasks": {
                    "bootstrap": {
                        "selected": {
                            "mcp_server_ids": ["http-mcp", "kali"],
                            "skill_ids": ["cypher-ctf", "missing-skill"],
                        },
                        "snapshots": [
                            {"kind": "mcp_server", "capability_id": "http-mcp", "source": "selected"},
                            {"kind": "mcp_server", "capability_id": "kali", "source": "selected"},
                            {"kind": "skill", "capability_id": "cypher-ctf", "source": "selected"},
                            {"kind": "skill", "capability_id": "missing-skill", "source": "selected"},
                        ],
                    },
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
                "unavailable": {
                    "mcp_server_ids": ["old-mcp"],
                    "skill_ids": ["missing-skill"],
                },
            },
        )

        self.assertEqual(payload["summary"], "Project capabilities before bootstrap: 2 MCP servers, 2 skills")
        self.assertEqual(payload["project_id"], "proj_001")
        self.assertTrue(payload["mcp_servers"][0]["enabled_for_task"])
        self.assertFalse(payload["mcp_servers"][1]["enabled_for_task"])
        self.assertTrue(payload["skills"][0]["enabled_for_task"])
        self.assertFalse(payload["skills"][1]["available"])
        self.assertEqual(payload["unavailable"]["mcp_server_ids"], ["old-mcp"])
        self.assertEqual(payload["unavailable"]["skill_ids"], ["missing-skill"])
        rendered = repr(payload)
        self.assertNotIn("should-not-appear", rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("TOKEN", rendered)

    def test_manifest_empty_when_selection_unavailable(self) -> None:
        from cairn.shared.capability_projection import capability_manifest_payload

        payload = capability_manifest_payload("proj_002", "bootstrap", None)

        self.assertEqual(payload["mcp_servers"], [])
        self.assertEqual(payload["skills"], [])
        self.assertIn("no capability selection available", payload["summary"])

    def test_dispatcher_catalog_payload_carries_probe_and_routing_fields(self) -> None:
        from cairn.dispatcher.capabilities import catalog_payload
        from cairn.shared.config import (
            McpServerCapabilityConfig,
            SkillCapabilityConfig,
        )
        config = SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="kali-server-mcp",
                        name="Kali",
                        transport="stdio",
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

    def test_injection_prefers_execution_config_catalog_snapshot(self) -> None:
        from cairn.dispatcher.capabilities import inject_project_capabilities
        from cairn.shared.config import McpServerCapabilityConfig, SkillCapabilityConfig

        config = SimpleNamespace(
            servers=[],
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="snap-mcp",
                        name="Current MCP",
                        transport="stdio",
                        command="current-mcp",
                        task_types=["explore"],
                    )
                ],
                skills=[
                    SkillCapabilityConfig(
                        id="snap-skill",
                        name="Current Skill",
                        source_path="/current/skill",
                        task_types=["explore"],
                    )
                ],
            ),
        )
        writer = mock.MagicMock()

        result = inject_project_capabilities(
            config,  # type: ignore[arg-type]
            None,
            writer,
            "container",
            "proj",
            "explore",
            "intent",
            {
                "catalog": [
                    {
                        "kind": "mcp_server",
                        "id": "snap-mcp",
                        "name": "Snapshot MCP",
                        "transport": "stdio",
                        "command": "snapshot-mcp",
                        "task_types": ["explore"],
                    },
                    {
                        "kind": "skill",
                        "id": "snap-skill",
                        "name": "Snapshot Skill",
                        "source_path": "/snapshot/skill",
                        "task_types": ["explore"],
                    },
                ],
                "tasks": {
                    "explore": {
                        "snapshots": [
                            {"kind": "mcp_server", "capability_id": "snap-mcp"},
                            {"kind": "skill", "capability_id": "snap-skill"},
                        ],
                    }
                },
            },
        )

        self.assertIn("snap-mcp", result.mcp_servers)
        self.assertIn("snap-skill", result.skills)
        writer.write_directory.assert_any_call("container", mock.ANY, Path("/snapshot/skill"))


class DispatcherCatalogPayloadRequiredSkillIdsTests(unittest.TestCase):
    """catalog_payload carries required_skill_ids for MCP entries."""

    def test_payload_includes_required_skill_ids(self) -> None:
        from types import SimpleNamespace

        from cairn.dispatcher.capabilities import catalog_payload
        from cairn.shared.config import (
            McpServerCapabilityConfig,
            SkillCapabilityConfig,
        )
        config = SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="camoufox-reverse",
                        name="Camoufox",
                        transport="stdio",
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
        from cairn.dispatcher.capability_instructions import instructions
        from cairn.shared.config import McpServerCapabilityConfig, SkillCapabilityConfig

        text = instructions(
            "/tmp/cap/mcp.json",
            "/tmp/cap/skills",
            [
                McpServerCapabilityConfig(
                    id="chrome-devtools-host",
                    name="Host Chrome DevTools MCP",
                    transport="stdio",
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

    def test_execute_instructions_render_files_appendix_as_separate_section(self) -> None:
        from cairn.dispatcher.capability_instructions import instructions

        text = instructions(
            "/tmp/cap/mcp.json",
            "/tmp/cap/skills",
            [],
            [],
            files_appendix="Use relative paths.\n\n- reports/ stores summaries.",
        )

        self.assertIn("## Files", text)
        self.assertIn("Use relative paths.", text)
        self.assertIn("reports/ stores summaries.", text)
        self.assertLess(text.index("## Files"), text.index("Use these capabilities only for the current Cairn project/challenge."))

    def test_execute_instructions_render_resources_as_subsection(self) -> None:
        from cairn.dispatcher.capability_instructions import instructions

        text = instructions(
            "/tmp/cap/mcp.json",
            "/tmp/cap/skills",
            [],
            [],
            resources_appendix="Servers are global AI-accessible remote server capabilities.\n\n- srv1: ops@host:22",
        )

        self.assertIn("# Project Capabilities", text)
        self.assertIn("## Servers And Project Proxy", text)
        self.assertIn("srv1: ops@host:22", text)
        self.assertNotIn("# Servers And Project Proxy", text.splitlines())
        self.assertLess(
            text.index("## Servers And Project Proxy"),
            text.index("Use these capabilities only for the current Cairn project/challenge."),
        )

    def test_reason_instructions_render_metadata_without_paths(self) -> None:
        from cairn.dispatcher.capability_instructions import reason_instructions
        from cairn.shared.config import McpServerCapabilityConfig, SkillCapabilityConfig

        text = reason_instructions(
            [
                McpServerCapabilityConfig(
                    id="chrome-devtools-host",
                    name="Host Chrome DevTools MCP",
                    transport="stdio",
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
        self.assertNotIn("## Files", text)

    def test_load_prompt_files_appendix_reads_file_outputs_document(self) -> None:
        from cairn.dispatcher import prompt_resources as mod

        with tempfile.TemporaryDirectory() as tmp:
            group_dir = Path(tmp) / "default"
            group_dir.mkdir()
            (group_dir / "FILE_OUTPUTS.md").write_text("Use reports/.\n", encoding="utf-8")
            with mock.patch.object(mod.resources, "files") as files:
                files.return_value.joinpath.side_effect = lambda group: Path(tmp) / group
                text, errors = mod.load_prompt_files_appendix()

        self.assertEqual(text, "Use reports/.")
        self.assertEqual(errors, [])

    def test_load_prompt_files_appendix_reports_missing_file(self) -> None:
        from cairn.dispatcher import prompt_resources as mod

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(mod.resources, "files") as files:
                files.return_value.joinpath.side_effect = lambda group: Path(tmp) / group
                text, errors = mod.load_prompt_files_appendix()

        self.assertEqual(text, "")
        self.assertEqual(errors, ["files: prompt group default missing FILE_OUTPUTS.md"])


if __name__ == "__main__":
    unittest.main()
