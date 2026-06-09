from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class DispatchSidecarConfigTests(unittest.TestCase):
    def test_capabilities_sidecar_merges_into_dispatch_config(self) -> None:
        from cairn.dispatcher.config import DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "dispatch.yaml").write_text(
                """
server: http://server
runtime:
  interval: 3
  max_workers: 1
  max_running_projects: 1
  max_project_workers: 1
  healthcheck_timeout: 1
  prompt_group: cypher
tasks:
  bootstrap: {timeout: 1, conclude_timeout: 1}
  reason: {timeout: 1, max_intents: 1}
  explore: {timeout: 1, conclude_timeout: 1}
container:
  image: img
  network_mode: bridge
  completed_action: stop
workers:
  - name: mock
    type: mock
    priority: 1
    max_running: 1
    task_types: [bootstrap, explore, reason]
    env: {}
""".strip(),
                encoding="utf-8",
            )
            (root / "dispatch.capabilities.yaml").write_text(
                """
capabilities:
  mcp_servers:
    - id: mcp1
      name: MCP
      description: desc
      command: echo
      args: []
      task_types: [explore]
  skills: []
roles:
  - id: role1
    name: Role
    description: desc
    prompt: prompt
    task_types: [reason]
remote_support:
  enabled: true
""".strip(),
                encoding="utf-8",
            )
            cfg = DispatchConfig.load(root / "dispatch.yaml")
        self.assertEqual(len(cfg.capabilities.mcp_servers), 1)
        self.assertEqual(cfg.capabilities.mcp_servers[0].id, "mcp1")
        self.assertEqual(len(cfg.roles), 1)
        self.assertTrue(cfg.remote_support.enabled)

    def test_role_default_skill_ids_resolve(self) -> None:
        from cairn.dispatcher.config import DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "skill").mkdir()
            (root / "role.md").write_text("role prompt", encoding="utf-8")
            (root / "dispatch.yaml").write_text(
                """
server: http://server
runtime:
  interval: 3
  max_workers: 1
  max_running_projects: 1
  max_project_workers: 1
  healthcheck_timeout: 1
  prompt_group: cypher
tasks:
  bootstrap: {timeout: 1, conclude_timeout: 1}
  reason: {timeout: 1, max_intents: 1}
  explore: {timeout: 1, conclude_timeout: 1}
container:
  image: img
  network_mode: bridge
  completed_action: stop
capabilities:
  skills:
    - id: skill1
      name: Skill
      source_path: ./skill
workers:
  - name: mock
    type: mock
    priority: 1
    max_running: 1
    task_types: [bootstrap, explore, reason]
    env: {}
roles:
  - id: role1
    name: Role
    source_path: ./role.md
    default_skill_ids: [skill1]
""".strip(),
                encoding="utf-8",
            )
            cfg = DispatchConfig.load(root / "dispatch.yaml")

        self.assertEqual(cfg.roles[0].default_skill_ids, ["skill1"])

    def test_role_default_skill_ids_must_resolve(self) -> None:
        from cairn.dispatcher.config import DispatchConfig
        from pydantic import ValidationError

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "role.md").write_text("role prompt", encoding="utf-8")
            (root / "dispatch.yaml").write_text(
                """
server: http://server
runtime:
  interval: 3
  max_workers: 1
  max_running_projects: 1
  max_project_workers: 1
  healthcheck_timeout: 1
  prompt_group: cypher
tasks:
  bootstrap: {timeout: 1, conclude_timeout: 1}
  reason: {timeout: 1, max_intents: 1}
  explore: {timeout: 1, conclude_timeout: 1}
container:
  image: img
  network_mode: bridge
  completed_action: stop
workers:
  - name: mock
    type: mock
    priority: 1
    max_running: 1
    task_types: [bootstrap, explore, reason]
    env: {}
roles:
  - id: role1
    name: Role
    source_path: ./role.md
    default_skill_ids: [missing-skill]
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaises(ValidationError) as ctx:
                DispatchConfig.load(root / "dispatch.yaml")

        self.assertIn("missing-skill", str(ctx.exception))

    def test_repo_capability_routing_metadata_loads_from_sidecar(self) -> None:
        from cairn.dispatcher.config import DispatchConfig

        old_env = {
            key: os.environ.get(key)
            for key in (
                "CAIRN_DISPATCHER_DATAS_ROOT",
                "ANTHROPIC_AUTH_TOKEN",
                "OPENAI_API_KEY",
            )
        }
        os.environ["CAIRN_DISPATCHER_DATAS_ROOT"] = "/tmp/cairn-test"
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "test"
        os.environ["OPENAI_API_KEY"] = "test"
        try:
            cfg = DispatchConfig.load(_REPO / "dispatch.yaml")
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        mcp_by_id = {item.id: item for item in cfg.capabilities.mcp_servers}
        skill_by_id = {item.id: item for item in cfg.capabilities.skills}
        self.assertEqual(mcp_by_id["kali-server-mcp"].required_skill_ids, [])
        self.assertEqual(mcp_by_id["metasploit-mcp"].required_skill_ids, [])
        self.assertTrue(mcp_by_id["kali-server-mcp"].use_when)
        self.assertTrue(mcp_by_id["metasploit-mcp"].use_when)
        self.assertIn("Kali command", mcp_by_id["kali-server-mcp"].activation_hint)
        self.assertIn("authorized scope", mcp_by_id["metasploit-mcp"].activation_hint)
        self.assertTrue(skill_by_id["cypher-ctf"].use_when)
        self.assertTrue(skill_by_id["cypher-pentest"].use_when)
        self.assertIn("SKILL.md", skill_by_id["cypher-ctf"].activation_hint)
        self.assertIn("scope/ROE", skill_by_id["cypher-pentest"].activation_hint)
        role_by_id = {item.id: item for item in cfg.roles}
        self.assertEqual(role_by_id["cypher-ctf-operator"].default_skill_ids, ["cypher-ctf"])
        self.assertEqual(role_by_id["cypher-pentest-operator"].default_skill_ids, ["cypher-pentest"])
        self.assertEqual(role_by_id["cypher-vuln-researcher"].default_skill_ids, ["cypher-vuln-research"])


if __name__ == "__main__":
    unittest.main()
