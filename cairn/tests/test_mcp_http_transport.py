"""Stage 7: write unit tests for HTTP transport + bearer token + probe + redaction."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow running tests without installing the package.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class McpServerCapabilityConfigHttpTests(unittest.TestCase):
    """Schema validation for transport=http and bearer_token_env."""

    def setUp(self):
        from cairn.dispatcher.config import McpServerCapabilityConfig
        self.McpServerCapabilityConfig = McpServerCapabilityConfig

    def test_stdio_default_no_transport_field(self):
        # back-compat: legacy entries without transport default to stdio
        m = self.McpServerCapabilityConfig(id="x", name="x", command="/bin/true")
        self.assertEqual(m.transport, "stdio")

    def test_http_with_url_only(self):
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="http", url="https://example.com/mcp"
        )
        self.assertEqual(m.transport, "http")
        self.assertEqual(m.url, "https://example.com/mcp")

    def test_http_requires_url(self):
        with self.assertRaises(Exception) as cm:
            self.McpServerCapabilityConfig(id="x", name="x", transport="http")
        self.assertIn("http transport requires 'url'", str(cm.exception))

    def test_stdio_requires_command(self):
        with self.assertRaises(Exception) as cm:
            self.McpServerCapabilityConfig(id="x", name="x", transport="stdio")
        self.assertIn("stdio transport requires 'command'", str(cm.exception))

    def test_http_url_must_start_with_http_or_https(self):
        for bad in ("ftp://x", "x://x", "/path", "example.com"):
            with self.subTest(bad=bad):
                with self.assertRaises(Exception) as cm:
                    self.McpServerCapabilityConfig(
                        id="x", name="x", transport="http", url=bad
                    )
                self.assertIn("url must start with http", str(cm.exception))

    def test_http_bearer_token_env_requires_env_set(self):
        old = os.environ.pop("DEFINITELY_NOT_SET_XYZ", None)
        try:
            with self.assertRaises(Exception) as cm:
                self.McpServerCapabilityConfig(
                    id="x", name="x", transport="http",
                    url="https://example.com",
                    bearer_token_env="DEFINITELY_NOT_SET_XYZ",
                )
            self.assertIn("not set in the dispatcher process", str(cm.exception))
        finally:
            if old is not None:
                os.environ["DEFINITELY_NOT_SET_XYZ"] = old

    def test_http_bearer_token_env_passes_when_env_set(self):
        os.environ["MCP_TEST_TOKEN"] = "tk-1"
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="http",
            url="https://example.com", bearer_token_env="MCP_TEST_TOKEN",
        )
        self.assertEqual(m.bearer_token_env, "MCP_TEST_TOKEN")
        del os.environ["MCP_TEST_TOKEN"]

    def test_stdio_with_bearer_token_env_rejected(self):
        os.environ["MCP_TEST_TOKEN"] = "tk-1"
        try:
            with self.assertRaises(Exception) as cm:
                self.McpServerCapabilityConfig(
                    id="x", name="x", transport="stdio", command="/bin/true",
                    bearer_token_env="MCP_TEST_TOKEN",
                )
            self.assertIn("only valid for http transport", str(cm.exception))
        finally:
            del os.environ["MCP_TEST_TOKEN"]

    def test_healthcheck_timeout_bounds(self):
        with self.assertRaises(Exception):
            self.McpServerCapabilityConfig(
                id="x", name="x", transport="http", url="https://x",
                healthcheck_timeout=0,
            )
        with self.assertRaises(Exception):
            self.McpServerCapabilityConfig(
                id="x", name="x", transport="http", url="https://x",
                healthcheck_timeout=100,
            )


class DispatchConfigInterpTests(unittest.TestCase):
    """${ENV_VAR} interpolation skip for bearer_token_env."""

    def setUp(self):
        os.environ["MCP_TEST_TOKEN"] = "tk-1"
        os.environ["MY_HOST"] = "h.local"

    def tearDown(self):
        os.environ.pop("MCP_TEST_TOKEN", None)
        os.environ.pop("MY_HOST", None)

    def _write_yaml(self, body: str) -> Path:
        f = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w")
        f.write(body)
        f.close()
        return Path(f.name)

    def test_bearer_token_env_preserved_as_literal_name(self):
        from cairn.dispatcher.config import DispatchConfig

        yaml = """
server: "http://x"
runtime:
  interval: 3
  max_workers: 1
  max_running_projects: 1
  max_project_workers: 1
  healthcheck_timeout: 1
  prompt_group: "default"
tasks:
  bootstrap: {timeout: 1, conclude_timeout: 1}
  reason: {timeout: 1, max_intents: 1}
  explore: {timeout: 1, conclude_timeout: 1}
container:
  image: "x:latest"
  network_mode: "cairn"
  completed_action: "stop"
capabilities:
  mcp_servers:
    - id: "h"
      name: "h"
      transport: "http"
      url: "https://${MY_HOST}/mcp"
      bearer_token_env: "MCP_TEST_TOKEN"
      task_types: ["bootstrap"]
workers:
  - name: "m"
    type: "mock"
    task_types: [bootstrap, reason, explore]
    max_running: 1
    priority: 0
    env: {}
"""
        p = self._write_yaml(yaml)
        try:
            cfg = DispatchConfig.load(p)
            mcp = cfg.capabilities.mcp_servers[0]
            # bearer_token_env stays as the literal name
            self.assertEqual(mcp.bearer_token_env, "MCP_TEST_TOKEN")
            # url was interpolated
            self.assertEqual(mcp.url, "https://h.local/mcp")
        finally:
            p.unlink()


class McpInjectionTests(unittest.TestCase):
    """_mcp_config_detail / _mcp_json / _mcp_detail shape per transport."""

    def setUp(self):
        os.environ["MCP_TEST_TOKEN"] = "tk-1"
        from cairn.dispatcher.config import McpServerCapabilityConfig
        self.McpServerCapabilityConfig = McpServerCapabilityConfig

    def tearDown(self):
        os.environ.pop("MCP_TEST_TOKEN", None)

    def test_stdio_detail_shape(self):
        from cairn.dispatcher.capabilities import _mcp_config_detail
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="stdio", command="/bin/true",
            args=["--flag"], env={"K": "V"},
        )
        d = _mcp_config_detail(m, "/cap")
        self.assertEqual(d["command"], "/bin/true")
        self.assertEqual(d["args"], ["--flag"])
        self.assertEqual(d["env"], {"K": "V"})
        # no http-specific keys
        self.assertNotIn("type", d)
        self.assertNotIn("url", d)

    def test_http_detail_without_bearer(self):
        from cairn.dispatcher.capabilities import _mcp_config_detail
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="http", url="https://example.com/mcp",
        )
        d = _mcp_config_detail(m, "/cap")
        self.assertEqual(d["type"], "http")
        self.assertEqual(d["url"], "https://example.com/mcp")
        self.assertNotIn("headers", d)

    def test_http_detail_with_bearer_resolves_token(self):
        from cairn.dispatcher.capabilities import _mcp_config_detail
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="http", url="https://example.com/mcp",
            bearer_token_env="MCP_TEST_TOKEN",
        )
        d = _mcp_config_detail(m, "/cap")
        self.assertEqual(d["type"], "http")
        self.assertEqual(d["headers"], {"Authorization": "Bearer tk-1"})

    def test_mcp_json_for_mixed_transport(self):
        from cairn.dispatcher.capabilities import _mcp_json
        stdio = self.McpServerCapabilityConfig(
            id="s", name="s", transport="stdio", command="/bin/true",
        )
        http = self.McpServerCapabilityConfig(
            id="h", name="h", transport="http", url="https://example.com/mcp",
            bearer_token_env="MCP_TEST_TOKEN",
        )
        rendered = _mcp_json([stdio, http], "/cap")
        parsed = json.loads(rendered)
        self.assertIn("mcpServers", parsed)
        self.assertEqual(parsed["mcpServers"]["s"]["command"], "/bin/true")
        self.assertEqual(parsed["mcpServers"]["h"]["type"], "http")
        self.assertEqual(
            parsed["mcpServers"]["h"]["headers"]["Authorization"],
            "Bearer tk-1",
        )

    def test_mcp_detail_includes_transport_and_bearer_env(self):
        from cairn.dispatcher.capabilities import _mcp_detail
        m = self.McpServerCapabilityConfig(
            id="h", name="h", transport="http", url="https://example.com",
            bearer_token_env="MCP_TEST_TOKEN",
        )
        d = _mcp_detail(m, "/cap")
        self.assertEqual(d["id"], "h")
        self.assertEqual(d["transport"], "http")
        self.assertEqual(d["bearer_token_env"], "MCP_TEST_TOKEN")
        # token value NOT included in detail (it lives in mcp.json's
        # headers only, populated at injection time)
        self.assertNotIn("headers", d)

    def test_chrome_devtools_stdio_args_resolve_host_alias(self):
        from cairn.dispatcher.capabilities import _mcp_config_detail, _mcp_detail
        m = self.McpServerCapabilityConfig(
            id="chrome-devtools-host",
            name="Host Chrome",
            transport="stdio",
            command="chrome-devtools-mcp",
            args=["--browserUrl=http://host.docker.internal:9222"],
            probe_config={
                "type": "chrome_devtools_http",
                "url": "http://host.docker.internal:9222/json/version",
            },
            task_types=["bootstrap"],
        )
        with patch("socket.gethostbyname", return_value="0.250.250.254"):
            mcp_json_detail = _mcp_config_detail(m, "/cap")
            adapter_detail = _mcp_detail(m, "/cap")
        self.assertEqual(
            mcp_json_detail["args"],
            ["--browserUrl=http://0.250.250.254:9222"],
        )
        self.assertEqual(
            adapter_detail["args"],
            ["--browserUrl=http://0.250.250.254:9222"],
        )


class CapabilityProjectInjectionTests(unittest.TestCase):
    class FakeContainerManager:
        def __init__(self):
            self.directories = []
            self.files = []

        def write_directory(self, container_name, target_path, source_path):
            self.directories.append((container_name, target_path, source_path))

        def write_text_file(self, container_name, target_path, content):
            self.files.append((container_name, target_path, content))

    def _config(self, task_types):
        from types import SimpleNamespace
        from cairn.dispatcher.config import McpServerCapabilityConfig, SkillCapabilityConfig

        return SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="m",
                        name="MCP",
                        description="metadata mcp",
                        transport="stdio",
                        command="/bin/true",
                        task_types=task_types,
                    )
                ],
                skills=[
                    SkillCapabilityConfig(
                        id="s",
                        name="Skill",
                        description="metadata skill",
                        source_path="/tmp/skill",
                        task_types=task_types,
                    )
                ],
            )
        )

    def _selection(self):
        return {
            "per_task": {
                "bootstrap": {"mcp_server_ids": ["m"], "skill_ids": ["s"]},
                "explore": {"mcp_server_ids": ["m"], "skill_ids": ["s"]},
                "reason": {"mcp_server_ids": ["m"], "skill_ids": ["s"]},
            }
        }

    def test_explore_injection_writes_runtime_capability_resources(self):
        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            self._config(["explore", "reason"]),
            manager,
            "worker",
            "proj",
            "explore",
            "task",
            self._selection(),
        )

        self.assertEqual(result.mcp_servers, ["m"])
        self.assertEqual(result.skills, ["s"])
        self.assertIn("MCP server config file", result.instructions)
        self.assertIn("Skill directory root", result.instructions)
        self.assertEqual(len(manager.files), 1)
        self.assertEqual(len(manager.directories), 1)
        self.assertEqual(result.context.mcp_config_path, "/tmp/cairn-capabilities/proj/task/mcp.json")
        self.assertEqual(result.context.skill_root, "/tmp/cairn-capabilities/proj/task/skills")

    def test_reason_injection_uses_metadata_only_without_runtime_resources(self):
        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            self._config(["explore", "reason"]),
            manager,
            "worker",
            "proj",
            "reason",
            "task",
            self._selection(),
        )

        self.assertEqual(result.mcp_servers, ["m"])
        self.assertEqual(result.skills, ["s"])
        self.assertIn("intent design only", result.instructions)
        self.assertIn("m: MCP - metadata mcp", result.instructions)
        self.assertIn("s: Skill - metadata skill", result.instructions)
        self.assertNotIn("mcp.json", result.instructions)
        self.assertNotIn("Skill directory root", result.instructions)
        self.assertEqual(manager.files, [])
        self.assertEqual(manager.directories, [])
        self.assertEqual(result.context.mcp_config_path, "")
        self.assertEqual(result.context.skill_root, "")

    def test_reason_skips_capabilities_not_enabled_for_reason(self):
        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            self._config(["explore"]),
            manager,
            "worker",
            "proj",
            "reason",
            "task",
            self._selection(),
        )

        self.assertEqual(result.instructions, "")
        self.assertEqual(result.mcp_servers, [])
        self.assertEqual(result.skills, [])
        self.assertEqual(manager.files, [])
        self.assertEqual(manager.directories, [])


class CodexAdapterHttpTests(unittest.TestCase):
    """Codex adapter emits -c mcp_servers.<id>.url and bearer_token_env_var."""

    def _context(self, mcp_servers):
        from cairn.dispatcher.workers.base import WorkerExecutionContext
        return WorkerExecutionContext(
            capability_root="/cap",
            mcp_config_path="/cap/mcp.json",
            skill_root="/cap/skills",
            mcp_servers=mcp_servers,
            skills=[],
        )

    def test_stdio_emits_command(self):
        from cairn.dispatcher.workers.adapters.codex import CodexDriver
        ctx = self._context([{
            "id": "s", "transport": "stdio", "command": "/bin/true",
            "args": ["--flag"], "env": {"K": "V"},
        }])
        argv = CodexDriver._capability_args(ctx)
        joined = " ".join(argv)
        self.assertIn('mcp_servers.s.command="/bin/true"', joined)
        self.assertIn('mcp_servers.s.args=["--flag"]', joined)
        self.assertIn('mcp_servers.s.env.K="V"', joined)
        self.assertNotIn("mcp_servers.s.url", joined)

    def test_http_emits_url_and_bearer_token_env_var(self):
        from cairn.dispatcher.workers.adapters.codex import CodexDriver
        ctx = self._context([{
            "id": "h", "transport": "http",
            "url": "https://example.com/mcp",
            "bearer_token_env": "MCP_AUTH_TOKEN",
        }])
        argv = CodexDriver._capability_args(ctx)
        joined = " ".join(argv)
        self.assertIn('mcp_servers.h.url="https://example.com/mcp"', joined)
        self.assertIn('mcp_servers.h.bearer_token_env_var="MCP_AUTH_TOKEN"', joined)
        self.assertNotIn("mcp_servers.h.command", joined)

    def test_http_without_bearer_emits_only_url(self):
        from cairn.dispatcher.workers.adapters.codex import CodexDriver
        ctx = self._context([{
            "id": "h", "transport": "http",
            "url": "https://example.com/mcp",
        }])
        argv = CodexDriver._capability_args(ctx)
        joined = " ".join(argv)
        self.assertIn('mcp_servers.h.url="https://example.com/mcp"', joined)
        self.assertNotIn("bearer_token_env_var", joined)


class RedactionTests(unittest.TestCase):
    """BUILTIN_PATTERNS cover Authorization: Bearer <token>."""

    def test_bearer_token_redacted_in_dispatcher_module(self):
        from cairn.dispatcher.observability.redaction import redact_content
        out, changed = redact_content("Authorization: Bearer tk-12345abcdef", [])
        self.assertTrue(changed)
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("tk-12345abcdef", out)

    def test_bearer_token_redacted_in_server_module(self):
        from cairn.server.observability.redaction import redact_content
        out, changed = redact_content("Authorization: Bearer tk-12345abcdef", [])
        self.assertTrue(changed)
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("tk-12345abcdef", out)

    def test_authorization_header_in_json_line(self):
        from cairn.dispatcher.observability.redaction import redact_content
        line = '{"request": {"headers": {"Authorization": "Bearer tk-abc"}}}'
        out, changed = redact_content(line, [])
        self.assertTrue(changed)
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("tk-abc", out)


class HttpProbeTests(unittest.TestCase):
    """_probe_http_url uses socket.create_connection."""

    def test_unreachable_host_returns_false(self):
        from cairn.dispatcher.capabilities import _probe_http_url
        # 192.0.2.0/24 is TEST-NET-1, guaranteed not to be routed
        ok, reason = _probe_http_url("http://192.0.2.1:1/mcp", 0.5)
        self.assertFalse(ok)
        self.assertNotEqual(reason, "")

    def test_localhost_reachable_or_unreachable_based_on_env(self):
        # We can't reliably start a server in this unit test, so we just
        # verify the function runs without exception and returns (bool, str).
        from cairn.dispatcher.capabilities import _probe_http_url
        ok, reason = _probe_http_url("http://127.0.0.1:1/mcp", 0.2)
        # Either ok=True (something is listening) or ok=False with a reason
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(reason, str)

    def test_url_with_no_host_returns_false(self):
        from cairn.dispatcher.capabilities import _probe_http_url
        ok, reason = _probe_http_url("http:///nopath", 0.2)
        self.assertFalse(ok)
        self.assertEqual(reason, "url has no host")

    def test_validate_selected_mcp_uses_chrome_devtools_probe(self):
        from cairn.dispatcher.capabilities import _validate_selected_mcp
        from cairn.dispatcher.config import McpServerCapabilityConfig
        mcp = McpServerCapabilityConfig(
            id="chrome-devtools-host",
            name="Host Chrome",
            transport="stdio",
            command="chrome-devtools-mcp",
            probe_config={
                "type": "chrome_devtools_http",
                "url": "http://host.docker.internal:9222/json/version",
            },
            task_types=["bootstrap"],
        )
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/browser/abc"}'
        with patch("socket.gethostbyname", return_value="0.250.250.254"), patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            self.assertIsNone(_validate_selected_mcp(mcp, "bootstrap"))
        self.assertEqual(
            mock_urlopen.call_args.args[0],
            "http://0.250.250.254:9222/json/version",
        )

    def test_validate_selected_mcp_reports_missing_devtools_key(self):
        from cairn.dispatcher.capabilities import _validate_selected_mcp
        from cairn.dispatcher.config import McpServerCapabilityConfig
        mcp = McpServerCapabilityConfig(
            id="chrome-devtools-host",
            name="Host Chrome",
            transport="stdio",
            command="chrome-devtools-mcp",
            probe_config={
                "type": "chrome_devtools_http",
                "url": "http://host.docker.internal:9222/json/version",
            },
            task_types=["bootstrap"],
        )
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"Browser":"Chrome"}'
        with patch("socket.gethostbyname", return_value="0.250.250.254"), patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            error = _validate_selected_mcp(mcp, "bootstrap")
        self.assertEqual(
            error,
            "mcp_server:chrome-devtools-host: chrome devtools probe failed: missing json key: webSocketDebuggerUrl",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
