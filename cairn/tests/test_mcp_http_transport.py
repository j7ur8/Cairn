"""Stage 7: write unit tests for HTTP transport + bearer token + probe + redaction."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

# Allow running tests without installing the package.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class McpServerCapabilityConfigHttpTests(unittest.TestCase):
    """Schema validation for transport=http and direct headers."""

    def setUp(self):
        from cairn.shared.config import McpServerCapabilityConfig
        self.McpServerCapabilityConfig = McpServerCapabilityConfig

    def test_transport_is_required(self):
        with self.assertRaises(Exception) as cm:
            self.McpServerCapabilityConfig(id="x", name="x", command="/bin/true")
        self.assertIn("transport", str(cm.exception))

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

    def test_http_accepts_headers(self):
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="http",
            url="https://example.com", headers={"Authorization": "Bearer tk-1"},
        )
        self.assertEqual(m.headers, {"Authorization": "Bearer tk-1"})

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
    """Dispatch config loading keeps YAML values literal."""

    def _write_yaml(self, body: str) -> Path:
        from helpers import split_server_dispatch_config

        root = Path(tempfile.mkdtemp(prefix="cairn-mcp-config-"))
        path = root / "config.yaml"
        server, dispatch = split_server_dispatch_config(yaml.safe_load(body))
        (root / "server.yaml").write_text(yaml.safe_dump(server, sort_keys=False), encoding="utf-8")
        path.write_text(yaml.safe_dump(dispatch, sort_keys=False), encoding="utf-8")
        return path

    def test_dispatch_yaml_values_are_not_interpolated_from_env(self):
        from cairn.shared.config import DispatchConfig

        yaml = """
server:
  base_url: "http://x"
  database:
    url: postgresql+psycopg://cairn:cairn@localhost:5432/cairn
  auth:
    jwt_secret: test-jwt-secret-do-not-use-in-prod-32bytes
    dispatcher_api_token: test-dispatcher-token
  paths:
    datas_root: /tmp/cairn-test
  settings:
    intent_timeout: 5
    reason_timeout: 5
dispatcher:
  health_addr: "127.0.0.1:9100"
  reload:
    url: "http://127.0.0.1:9100/reload"
    enabled: false
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
worker_runtime:
  common_env: {}
  runner:
    image: "x:latest"
    network_mode: "cairn"
    completed_action: "stop"
worker_pool:
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
            (p.parent / "config.resources.yaml").write_text(
                """
capabilities:
  mcp_servers:
    - id: "h"
      name: "h"
      transport: "http"
      url: "https://example.test/mcp"
      headers:
        Authorization: "Bearer tk-direct"
      task_types: ["bootstrap"]
  skills: []
roles: []
""",
                encoding="utf-8",
            )
            cfg = DispatchConfig.load(p)
            mcp = cfg.capabilities.mcp_servers[0]
            self.assertEqual(mcp.url, "https://example.test/mcp")
            self.assertEqual(mcp.headers["Authorization"], "Bearer tk-direct")
        finally:
            import shutil
            shutil.rmtree(p.parent, ignore_errors=True)


class McpInjectionTests(unittest.TestCase):
    """MCP config and worker adapter detail shape per transport."""

    def setUp(self):
        from cairn.shared.config import McpServerCapabilityConfig
        self.McpServerCapabilityConfig = McpServerCapabilityConfig

    def test_stdio_detail_shape(self):
        from cairn.dispatcher.capability_mcp import mcp_config_detail
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="stdio", command="/bin/true",
            args=["--flag"], env={"K": "V"},
        )
        d = mcp_config_detail(m, "/cap")
        self.assertEqual(d["command"], "/bin/true")
        self.assertEqual(d["args"], ["--flag"])
        self.assertEqual(d["env"], {"K": "V"})
        # no http-specific keys
        self.assertNotIn("type", d)
        self.assertNotIn("url", d)

    def test_http_detail_without_bearer(self):
        from cairn.dispatcher.capability_mcp import mcp_config_detail
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="http", url="https://example.com/mcp",
        )
        d = mcp_config_detail(m, "/cap")
        self.assertEqual(d["type"], "http")
        self.assertEqual(d["url"], "https://example.com/mcp")
        self.assertNotIn("headers", d)

    def test_http_detail_with_headers(self):
        from cairn.dispatcher.capability_mcp import mcp_config_detail
        m = self.McpServerCapabilityConfig(
            id="x", name="x", transport="http", url="https://example.com/mcp",
            headers={"Authorization": "Bearer tk-1"},
        )
        d = mcp_config_detail(m, "/cap")
        self.assertEqual(d["type"], "http")
        self.assertEqual(d["headers"], {"Authorization": "Bearer tk-1"})

    def test_mcp_json_for_mixed_transport(self):
        from cairn.dispatcher.capability_mcp import mcp_json
        stdio = self.McpServerCapabilityConfig(
            id="s", name="s", transport="stdio", command="/bin/true",
        )
        http = self.McpServerCapabilityConfig(
            id="h", name="h", transport="http", url="https://example.com/mcp",
            headers={"Authorization": "Bearer tk-1"},
        )
        rendered = mcp_json([stdio, http], "/cap")
        parsed = json.loads(rendered)
        self.assertIn("mcpServers", parsed)
        self.assertEqual(parsed["mcpServers"]["s"]["command"], "/bin/true")
        self.assertEqual(parsed["mcpServers"]["h"]["type"], "http")
        self.assertEqual(
            parsed["mcpServers"]["h"]["headers"]["Authorization"],
            "Bearer tk-1",
        )

    def test_mcp_detail_includes_transport_and_headers(self):
        from cairn.dispatcher.capability_mcp import mcp_detail
        m = self.McpServerCapabilityConfig(
            id="h", name="h", transport="http", url="https://example.com",
            headers={"Authorization": "Bearer tk-1"},
        )
        d = mcp_detail(m, "/cap")
        self.assertEqual(d["id"], "h")
        self.assertEqual(d["transport"], "http")
        self.assertEqual(d["headers"], {"Authorization": "Bearer tk-1"})

    def test_chrome_devtools_stdio_args_resolve_host_alias(self):
        from cairn.dispatcher.capability_mcp import mcp_config_detail, mcp_detail
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
            mcp_json_detail = mcp_config_detail(m, "/cap")
            adapter_detail = mcp_detail(m, "/cap")
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

    class FakeToolSidecarManager:
        def __init__(self):
            self.ensure_calls = []

        def ensure_running(self, project_id, tool):
            self.ensure_calls.append((project_id, tool))
            return None

    def _config(self, task_types):
        from types import SimpleNamespace

        from cairn.shared.config import McpServerCapabilityConfig, SkillCapabilityConfig

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
            "tasks": {
                task: {
                    "selected": {"mcp_server_ids": ["m"], "skill_ids": ["s"]},
                    "snapshots": [
                        {"kind": "mcp_server", "capability_id": "m", "source": "selected"},
                        {"kind": "skill", "capability_id": "s", "source": "selected"},
                    ],
                }
                for task in ("bootstrap", "explore", "reason")
            }
        }

    def test_explore_injection_writes_runtime_capability_resources(self):
        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            self._config(["explore", "reason"]),
            None,
            manager,
            "worker",
            "proj",
            "explore",
            "task",
            self._selection(),
        )

        self.assertEqual(result.mcp_servers, ["m"])
        self.assertEqual(result.skills, ["s"])
        self.assertIn("Config file: /tmp/cairn-capabilities/proj/task/mcp.json", result.instructions)
        self.assertIn("Directory root: /tmp/cairn-capabilities/proj/task/skills", result.instructions)
        self.assertIn("native Skill tool", result.instructions)
        self.assertIn("Claude native Skill name: cairn-session-capabilities:s", result.instructions)
        self.assertIn("Description: metadata mcp", result.instructions)
        self.assertIn("Description: metadata skill", result.instructions)
        self.assertIn("## Files", result.instructions)
        self.assertIn("reports/", result.instructions)
        self.assertEqual(len(manager.files), 2)
        self.assertEqual(len(manager.directories), 2)
        self.assertEqual(result.context.mcp_config_path, "/tmp/cairn-capabilities/proj/task/mcp.json")
        self.assertEqual(result.context.skill_root, "/tmp/cairn-capabilities/proj/task/skills")
        self.assertEqual(result.context.claude_plugin_dir, "/tmp/cairn-capabilities/proj/task/claude-plugin")
        plugin_file = [item for item in manager.files if item[1].endswith("/.claude-plugin/plugin.json")][0]
        self.assertEqual(plugin_file[1], "/tmp/cairn-capabilities/proj/task/claude-plugin/.claude-plugin/plugin.json")
        self.assertIn('"name": "cairn-session-capabilities"', plugin_file[2])
        self.assertIn('"version": "0.0.0"', plugin_file[2])
        self.assertIn(
            ("worker", "/tmp/cairn-capabilities/proj/task/claude-plugin/skills/s", "/tmp/skill"),
            [(container, target, str(source)) for container, target, source in manager.directories],
        )

    def test_ctf_web_js_analysis_injection_writes_runtime_and_plugin_skill_directories(self):
        from types import SimpleNamespace

        from cairn.dispatcher.capabilities import inject_project_capabilities
        from cairn.shared.config import SkillCapabilityConfig

        skill_path = _REPO / "capabilities" / "skills" / "ctf-web-js-analysis"
        config = SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[],
                skills=[
                    SkillCapabilityConfig(
                        id="ctf-web-js-analysis",
                        name="CTF Web JS Analysis",
                        source_path=str(skill_path),
                        task_types=["explore"],
                    )
                ],
            )
        )
        selection = {
            "tasks": {
                "explore": {
                    "selected": {"mcp_server_ids": [], "skill_ids": ["ctf-web-js-analysis"]},
                    "snapshots": [
                        {"kind": "skill", "capability_id": "ctf-web-js-analysis", "source": "selected"},
                    ],
                },
            }
        }

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            config,
            None,
            manager,
            "worker",
            "proj",
            "explore",
            "task",
            selection,
        )

        self.assertEqual(result.skills, ["ctf-web-js-analysis"])
        self.assertEqual(len(manager.directories), 2)
        runtime_dir = [item for item in manager.directories if item[1].endswith("/skills/ctf-web-js-analysis")][0]
        _, target_path, source_path = runtime_dir
        self.assertEqual(target_path, "/tmp/cairn-capabilities/proj/task/skills/ctf-web-js-analysis")
        self.assertEqual(Path(source_path), skill_path)
        self.assertIn(
            ("worker", "/tmp/cairn-capabilities/proj/task/claude-plugin/skills/ctf-web-js-analysis", str(skill_path)),
            [(container, target, str(source)) for container, target, source in manager.directories],
        )
        self.assertTrue((Path(source_path) / "SKILL.md").exists())
        self.assertTrue((Path(source_path) / "references" / "workflow.md").exists())
        self.assertIn("ctf-web-js-analysis", result.instructions)

    def test_reason_injection_returns_no_capability_metadata_or_runtime_resources(self):
        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            self._config(["explore", "reason"]),
            None,
            manager,
            "worker",
            "proj",
            "reason",
            "task",
            self._selection(),
        )

        self.assertEqual(result.instructions, "")
        self.assertEqual(result.summary, "")
        self.assertEqual(result.mcp_servers, [])
        self.assertEqual(result.skills, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(manager.files, [])
        self.assertEqual(manager.directories, [])
        self.assertEqual(result.context.mcp_config_path, "")
        self.assertEqual(result.context.skill_root, "")
        self.assertEqual(result.context.claude_plugin_dir, "")

    def test_reason_skips_capabilities_not_enabled_for_reason(self):
        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            self._config(["explore"]),
            None,
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

    def test_explore_injection_includes_files_appendix_without_selected_capabilities(self):
        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            self._config(["reason"]),
            None,
            manager,
            "worker",
            "proj",
            "explore",
            "task",
            self._selection(),
        )

        self.assertEqual(result.mcp_servers, [])
        self.assertEqual(result.skills, [])
        self.assertIn("## Files", result.instructions)
        self.assertIn("reports/", result.instructions)
        self.assertEqual(manager.files, [])
        self.assertEqual(manager.directories, [])

    def test_explore_injection_uses_cairn_resources_hint_without_listing_resources(self):
        from types import SimpleNamespace

        from cairn.dispatcher.capabilities import inject_project_capabilities
        from cairn.shared.config import McpServerCapabilityConfig, ServerResourceConfig

        client = SimpleNamespace(
            list_project_proxy_endpoints=lambda _project_id: (_ for _ in ()).throw(
                AssertionError("project proxy endpoints must be queried through cairn-resources MCP")
            )
        )

        config = SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="cairn-resources",
                        name="Cairn Resources MCP",
                        transport="stdio",
                        command="/usr/local/bin/cairn-resources-mcp-stdio",
                        task_types=["bootstrap", "explore"],
                    )
                ],
                skills=[],
            ),
            servers=[
                ServerResourceConfig(
                    id="srv1",
                    name="Build host",
                    host="helper.example",
                    port=2222,
                    username="operator",
                    auth_order=["password"],
                    password="secret",
                )
            ],
        )

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            config,
            client,
            manager,
            "worker",
            "proj",
            "explore",
            "task",
            {
                "tasks": {
                    "explore": {
                        "selected": {"mcp_server_ids": ["cairn-resources"], "skill_ids": []},
                        "snapshots": [
                            {"kind": "mcp_server", "capability_id": "cairn-resources", "source": "selected"},
                        ],
                    }
                }
            },
        )

        self.assertEqual(result.mcp_servers, ["cairn-resources"])
        self.assertEqual(result.skills, [])
        self.assertIn("# Project Capabilities", result.instructions)
        self.assertIn("## Files", result.instructions)
        self.assertIn("## Servers And Project Proxy", result.instructions)
        self.assertIn("servers.list", result.instructions)
        self.assertIn("servers.run_command", result.instructions)
        self.assertIn("project_proxy.list_endpoints", result.instructions)
        self.assertIn("project_proxy.resolve_chain", result.instructions)
        self.assertIn("project_proxy.record_usage_result", result.instructions)
        self.assertNotIn("srv1: Build host", result.instructions)
        self.assertNotIn("auth_order=password", result.instructions)
        self.assertNotIn("proxy.internal", result.instructions)
        self.assertNotIn("secret", result.instructions)
        self.assertNotIn("# Servers And Project Proxy", result.instructions.splitlines())
        self.assertEqual(len(manager.files), 1)
        self.assertEqual(manager.directories, [])

    def test_explore_injection_excludes_resources_when_cairn_resources_not_selected(self):
        from types import SimpleNamespace

        from cairn.dispatcher.capabilities import inject_project_capabilities

        config = SimpleNamespace(
            capabilities=self._config(["reason"]).capabilities,
            servers=[],
        )

        manager = self.FakeContainerManager()
        result = inject_project_capabilities(
            config,
            SimpleNamespace(list_project_proxy_endpoints=lambda _project_id: [{"id": "px1"}]),
            manager,
            "worker",
            "proj",
            "explore",
            "task",
            self._selection(),
        )

        self.assertIn("## Files", result.instructions)
        self.assertNotIn("## Servers And Project Proxy", result.instructions)

    def test_explore_injection_reports_missing_files_appendix_without_blocking(self):
        from unittest.mock import patch

        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        with patch(
            "cairn.dispatcher.capabilities.load_prompt_files_appendix",
            return_value=("", ["files: prompt group default missing FILE_OUTPUTS.md"]),
        ):
            result = inject_project_capabilities(
                self._config(["explore"]),
                None,
                manager,
                "worker",
                "proj",
                "explore",
                "task",
                self._selection(),
            )

        self.assertEqual(result.mcp_servers, ["m"])
        self.assertEqual(result.skills, ["s"])
        self.assertNotIn("## Files", result.instructions)
        self.assertIn("files: prompt group default missing FILE_OUTPUTS.md", result.errors)
        self.assertIn('"errors": [\n    "files: prompt group default missing FILE_OUTPUTS.md"\n  ]', result.summary)

    def test_explore_injection_reports_empty_files_appendix_without_blocking(self):
        from unittest.mock import patch

        from cairn.dispatcher.capabilities import inject_project_capabilities

        manager = self.FakeContainerManager()
        with patch(
            "cairn.dispatcher.capabilities.load_prompt_files_appendix",
            return_value=("", ["files: prompt group default FILE_OUTPUTS.md is empty"]),
        ):
            result = inject_project_capabilities(
                self._config(["explore"]),
                None,
                manager,
                "worker",
                "proj",
                "explore",
                "task",
                self._selection(),
            )

        self.assertEqual(result.mcp_servers, ["m"])
        self.assertEqual(result.skills, ["s"])
        self.assertNotIn("## Files", result.instructions)
        self.assertIn("files: prompt group default FILE_OUTPUTS.md is empty", result.errors)

    def test_sidecar_mcp_selection_starts_project_sidecar_and_renders_http_url(self):
        from types import SimpleNamespace

        from cairn.dispatcher.capabilities import inject_project_capabilities
        from cairn.shared.config import McpServerCapabilityConfig

        config = SimpleNamespace(
            capabilities=SimpleNamespace(
                mcp_servers=[
                    McpServerCapabilityConfig(
                        id="kali-server-mcp",
                        name="Kali",
                        transport="http",
                        url="http://cairn-kali-{project_safe_id}:8765/mcp",
                        task_types=["explore"],
                    ),
                    McpServerCapabilityConfig(
                        id="metasploit-mcp",
                        name="Metasploit",
                        transport="http",
                        url="http://cairn-metasploit-{project_safe_id}:8775/mcp",
                        task_types=["explore"],
                    ),
                ],
                skills=[],
            )
        )
        selection = {
            "tasks": {
                "explore": {
                    "snapshots": [
                        {"kind": "mcp_server", "capability_id": "kali-server-mcp", "source": "selected"},
                        {"kind": "mcp_server", "capability_id": "metasploit-mcp", "source": "selected"},
                    ],
                }
            }
        }
        manager = self.FakeContainerManager()
        sidecars = self.FakeToolSidecarManager()

        result = inject_project_capabilities(
            config,
            None,
            manager,
            "worker",
            "proj/1",
            "explore",
            "task",
            selection,
            tool_sidecar_manager=sidecars,
        )

        self.assertEqual(sidecars.ensure_calls, [("proj/1", "kali"), ("proj/1", "metasploit")])
        self.assertEqual(result.mcp_servers, ["kali-server-mcp", "metasploit-mcp"])
        written = json.loads([item for item in manager.files if item[1].endswith("/mcp.json")][0][2])
        self.assertEqual(written["mcpServers"]["kali-server-mcp"]["type"], "http")
        self.assertEqual(written["mcpServers"]["kali-server-mcp"]["url"], "http://cairn-kali-proj-1:8765/mcp")
        self.assertEqual(written["mcpServers"]["metasploit-mcp"]["url"], "http://cairn-metasploit-proj-1:8775/mcp")


class CodexAdapterHttpTests(unittest.TestCase):
    """Codex adapter emits -c mcp_servers.<id>.url and headers."""

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

    def test_http_emits_url_and_headers(self):
        from cairn.dispatcher.workers.adapters.codex import CodexDriver
        ctx = self._context([{
            "id": "h", "transport": "http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer tk-1"},
        }])
        argv = CodexDriver._capability_args(ctx)
        joined = " ".join(argv)
        self.assertIn('mcp_servers.h.url="https://example.com/mcp"', joined)
        self.assertIn('mcp_servers.h.headers.Authorization="Bearer tk-1"', joined)
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
        self.assertNotIn("headers.Authorization", joined)


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
    """probe_http_url uses socket.create_connection."""

    def test_unreachable_host_returns_false(self):
        from cairn.dispatcher.capability_probe import probe_http_url
        # 192.0.2.0/24 is TEST-NET-1, guaranteed not to be routed
        ok, reason = probe_http_url("http://192.0.2.1:1/mcp", 0.5)
        self.assertFalse(ok)
        self.assertNotEqual(reason, "")

    def test_localhost_reachable_or_unreachable_based_on_env(self):
        # We can't reliably start a server in this unit test, so we just
        # verify the function runs without exception and returns (bool, str).
        from cairn.dispatcher.capability_probe import probe_http_url
        ok, reason = probe_http_url("http://127.0.0.1:1/mcp", 0.2)
        # Either ok=True (something is listening) or ok=False with a reason
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(reason, str)

    def test_url_with_no_host_returns_false(self):
        from cairn.dispatcher.capability_probe import probe_http_url
        ok, reason = probe_http_url("http:///nopath", 0.2)
        self.assertFalse(ok)
        self.assertEqual(reason, "url has no host")

    def test_validate_selected_mcp_uses_chrome_devtools_probe(self):
        from cairn.dispatcher.capability_probe import validate_selected_mcp
        from cairn.shared.config import McpServerCapabilityConfig
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
            self.assertIsNone(validate_selected_mcp(mcp, "bootstrap"))
        self.assertEqual(
            mock_urlopen.call_args.args[0],
            "http://0.250.250.254:9222/json/version",
        )

    def test_validate_selected_mcp_reports_missing_devtools_key(self):
        from cairn.dispatcher.capability_probe import validate_selected_mcp
        from cairn.shared.config import McpServerCapabilityConfig
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
            error = validate_selected_mcp(mcp, "bootstrap")
        self.assertEqual(
            error,
            "mcp_server:chrome-devtools-host: chrome devtools probe failed: missing json key: webSocketDebuggerUrl",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
