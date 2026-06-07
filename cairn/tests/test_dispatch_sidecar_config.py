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


if __name__ == "__main__":
    unittest.main()
