from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


CONFIG_YAML = """
server:
  settings:
    intent_timeout: 5
    reason_timeout: 5
dispatcher:
  runtime:
    interval: 3
    max_workers: 1
    max_running_projects: 1
    max_project_workers: 1
    healthcheck_timeout: 1
tasks:
  bootstrap: {timeout: 1, conclude_timeout: 1}
  reason: {timeout: 1, max_intents: 1}
  explore: {timeout: 1, conclude_timeout: 1}
worker_pool:
  proxies: []
  workers:
    - name: mock
      type: mock
      priority: 1
      max_running: 1
      task_types: [bootstrap, explore, reason]
      env: {}
"""

SERVER_YAML = """
server:
  base_url: http://server
  database:
    url: postgresql+psycopg://cairn:cairn@localhost:5432/cairn
  auth:
    jwt_secret: test-jwt-secret-do-not-use-in-prod-32bytes
    dispatcher_api_token: test-dispatcher-token
  paths:
    datas_root: /tmp/cairn-test
dispatcher:
  health_addr: 127.0.0.1:9100
  reload:
    url: http://127.0.0.1:9100/reload
    enabled: false
worker_runtime:
  common_env: {}
  container:
    image: img
    network_mode: bridge
    completed_action: stop
"""

EMPTY_RESOURCES = """
capabilities:
  mcp_servers: []
  skills: []
roles: []
""".strip()


def _write_base(root: Path) -> Path:
    """Write valid server.yaml + config.yaml + resources; return config path."""
    (root / "server.yaml").write_text(SERVER_YAML.strip(), encoding="utf-8")
    (root / "config.yaml").write_text(CONFIG_YAML.strip(), encoding="utf-8")
    (root / "config.resources.yaml").write_text(EMPTY_RESOURCES, encoding="utf-8")
    return root / "config.yaml"


class ConfigLoaderFailureTests(unittest.TestCase):
    """Regression tests for the config-load fail-fast boundary (ConfigError).

    These pin the operator-facing failure modes that previously surfaced as a
    bare IsADirectoryError crash-loop (missing bind-mount source) or an
    unhandled traceback.
    """

    def test_missing_resources_file_raises_config_error(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "server.yaml").write_text(SERVER_YAML.strip(), encoding="utf-8")
            (root / "config.yaml").write_text(CONFIG_YAML.strip(), encoding="utf-8")
            # No config.resources.yaml written.
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        self.assertIn("not found", str(ctx.exception))
        self.assertIn("config.resources.yaml", str(ctx.exception))

    def test_resources_path_is_directory_gives_bind_mount_hint(self) -> None:
        # Reproduces the real incident: a missing bind-mount source makes the
        # Docker daemon create an empty *directory* at the mount target.
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "server.yaml").write_text(SERVER_YAML.strip(), encoding="utf-8")
            (root / "config.yaml").write_text(CONFIG_YAML.strip(), encoding="utf-8")
            (root / "config.resources.yaml").mkdir()
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        message = str(ctx.exception)
        self.assertIn("directory", message)
        self.assertIn("bind-mount", message)

    def test_non_mapping_yaml_raises_config_error(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "server.yaml").write_text(SERVER_YAML.strip(), encoding="utf-8")
            (root / "config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
            (root / "config.resources.yaml").write_text(EMPTY_RESOURCES, encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        self.assertIn("must be a mapping", str(ctx.exception))

    def test_invalid_yaml_raises_config_error(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "server.yaml").write_text(SERVER_YAML.strip(), encoding="utf-8")
            (root / "config.yaml").write_text("server: [unterminated\n", encoding="utf-8")
            (root / "config.resources.yaml").write_text(EMPTY_RESOURCES, encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        self.assertIn("not valid YAML", str(ctx.exception))

    def test_schema_violation_raises_config_error(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # max_project_workers > max_workers violates the after-validator.
            bad = CONFIG_YAML.replace("max_project_workers: 1", "max_project_workers: 5")
            (root / "server.yaml").write_text(SERVER_YAML.strip(), encoding="utf-8")
            (root / "config.yaml").write_text(bad.strip(), encoding="utf-8")
            (root / "config.resources.yaml").write_text(EMPTY_RESOURCES, encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        self.assertIn("max_project_workers", str(ctx.exception))

    def test_missing_server_file_raises_config_error(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config.yaml").write_text(CONFIG_YAML.strip(), encoding="utf-8")
            (root / "config.resources.yaml").write_text(EMPTY_RESOURCES, encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        self.assertIn("server config not found", str(ctx.exception))
        self.assertIn("server.yaml", str(ctx.exception))

    def test_capability_skill_missing_source_path_raises_config_error(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_base(root)
            (root / "config.resources.yaml").write_text(
                """
capabilities:
  mcp_servers: []
  skills:
    - id: skill1
      name: Skill
      source_path: ./does-not-exist
roles: []
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        self.assertIn("source_path does not exist", str(ctx.exception))

    def test_role_source_path_must_be_file_not_dir(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_base(root)
            (root / "role-as-dir").mkdir()
            (root / "config.resources.yaml").write_text(
                """
capabilities:
  mcp_servers: []
  skills: []
roles:
  - id: role1
    name: Role
    source_path: ./role-as-dir
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                DispatchConfig.load(root / "config.yaml")
        self.assertIn("must be a file", str(ctx.exception))

    def test_valid_config_loads_without_error(self) -> None:
        # Guards against the failure-path checks rejecting a legitimately valid
        # config (false positives).
        from cairn.shared.config import DispatchConfig

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_path = _write_base(root)
            cfg = DispatchConfig.load(config_path)
        self.assertEqual(cfg.roles, [])
        self.assertEqual(cfg.capabilities.mcp_servers, [])
        self.assertEqual(cfg.server.base_url, "http://server")

    def test_mock_bootstrap_complete_outcome_keeps_legacy_config_compatible(self) -> None:
        from cairn.shared.config.mock_behavior import resolve_mock_behavior

        behavior = resolve_mock_behavior(
            "mock",
            {
                "MOCK_BOOTSTRAP": (
                    '{"delay":[0,0],"outcomes":{"complete":"1.0","fact":"0.0",'
                    '"rejected":"0.0","invalid_json":"0.0","invalid_payload":"0.0","command_fail":"0.0"}}'
                )
            },
        )

        self.assertEqual(behavior["bootstrap"]["outcomes"]["fact"], 1.0)

    def test_system_config_uses_explicit_server_path_override(self) -> None:
        from cairn.server import runtime_config

        old_dispatch_path = runtime_config.DEFAULT_DISPATCH_CONFIG_PATH
        old_server_path = runtime_config.DEFAULT_SERVER_CONFIG_PATH
        try:
            runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = _REPO / "config.test.yaml"
            runtime_config.DEFAULT_SERVER_CONFIG_PATH = _REPO / "server.test.yaml"
            runtime_config.reset_runtime_config_cache()
            self.assertEqual(
                runtime_config.system_config().database.url,
                "postgresql+psycopg://cairn:cairn@localhost:5432/cairn",
            )
        finally:
            runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = old_dispatch_path
            runtime_config.DEFAULT_SERVER_CONFIG_PATH = old_server_path
            runtime_config.reset_runtime_config_cache()


if __name__ == "__main__":
    unittest.main()
