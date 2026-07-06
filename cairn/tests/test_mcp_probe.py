from __future__ import annotations

import json
import unittest


def _dispatch_config_payload(mcp_servers: list[dict]) -> dict:
    return {
        "server": {
            "base_url": "http://server",
            "database": {"url": "postgresql://u:p@localhost/db"},
            "auth": {"jwt_secret": "secret", "dispatcher_api_token": "token"},
            "paths": {"datas_root": "/tmp/cairn"},
            "settings": {"intent_timeout": 5, "reason_timeout": 5},
        },
        "dispatcher": {
            "runtime": {
                "interval": 1,
                "max_workers": 1,
                "max_running_projects": 1,
                "max_project_workers": 1,
                "healthcheck_timeout": 1,
            }
        },
        "tasks": {
            "bootstrap": {"timeout": 5, "conclude_timeout": 5},
            "explore": {"timeout": 5, "conclude_timeout": 5},
            "reason": {"timeout": 5, "max_intents": 2},
        },
        "worker_runtime": {
            "container": {
                "image": "worker:latest",
                "network_mode": "bridge",
                "completed_action": "stop",
            },
            "common_env": {},
        },
        "worker_pool": {
            "workers": [
                {
                    "name": "mock",
                    "type": "mock",
                    "priority": 1,
                    "max_running": 1,
                    "task_types": ["bootstrap", "explore", "reason"],
                    "env": {},
                }
            ],
        },
        "resources": {
            "capabilities": {
                "mcp_servers": mcp_servers,
                "skills": [],
            },
            "roles": [],
        },
    }


class McpProbeRunnerTests(unittest.TestCase):
    def test_dispatcher_probe_uses_single_temp_container_and_cleans_up(self) -> None:
        from cairn.dispatcher.mcp_probe import MCP_PROBE_PATH, run_mcp_probe_request
        from cairn.dispatcher.runtime.process import ProcessResult
        from cairn.shared.config import DispatchConfig, McpServerCapabilityConfig

        cfg = DispatchConfig.model_validate(_dispatch_config_payload([
            McpServerCapabilityConfig(id="a", name="A", transport="stdio", command="/bin/a").model_dump(),
            McpServerCapabilityConfig(id="b", name="B", transport="stdio", command="/bin/b").model_dump(),
        ]))

        class _Process:
            def __init__(self, command):
                self.command = command

            def start(self):
                return None

            def communicate(self, timeout):
                return ProcessResult(returncode=0, stdout="initialize + tools/list ok\n", stderr="")

        class _ContainerManager:
            def __init__(self):
                self.created = 0
                self.removed = []
                self.writes = {}
                self.commands = []

            def create_startup_container(self):
                self.created += 1
                return "probe-container"

            def write_text_file(self, container_name, path, content):
                self.writes[path] = content

            def write_directory(self, container_name, path, source):
                self.writes[path] = str(source)

            def build_exec_process(self, container_name, env, command, timeout_seconds=None, **kwargs):
                self.commands.append(command)
                return _Process(command)

            def remove_container(self, container_name, force=True):
                self.removed.append((container_name, force))

        manager = _ContainerManager()
        payload = run_mcp_probe_request(config=cfg, container_manager=manager, server_ids=["a", "b"])

        self.assertEqual(manager.created, 1)
        self.assertEqual(manager.removed, [("probe-container", True)])
        written = json.loads(manager.writes[MCP_PROBE_PATH])
        self.assertEqual(sorted(written["mcpServers"]), ["a", "b"])
        self.assertEqual([cmd[-1] for cmd in manager.commands], ["a", "b"])
        self.assertEqual([item["status"] for item in payload["results"]], ["ok", "ok"])

    def test_dispatcher_probe_reports_failed_exec(self) -> None:
        from cairn.dispatcher.mcp_probe import run_mcp_probe_request
        from cairn.dispatcher.runtime.process import ProcessResult
        from cairn.shared.config import DispatchConfig

        cfg = DispatchConfig.model_validate(_dispatch_config_payload([
            {"id": "chrome", "name": "Chrome", "transport": "stdio", "command": "chrome-devtools-mcp"},
        ]))

        class _Process:
            def start(self):
                return None

            def communicate(self, timeout):
                return ProcessResult(returncode=1, stdout="", stderr="connect ECONNREFUSED 127.0.0.1:9333")

        class _ContainerManager:
            def create_startup_container(self):
                return "probe-container"

            def write_text_file(self, *args):
                return None

            def write_directory(self, *args):
                return None

            def build_exec_process(self, *args, **kwargs):
                return _Process()

            def remove_container(self, *args, **kwargs):
                return None

        payload = run_mcp_probe_request(config=cfg, container_manager=_ContainerManager(), server_ids=["chrome"])
        self.assertEqual(payload["results"][0]["status"], "error")
        self.assertIn("ECONNREFUSED", payload["results"][0]["message"])

    def test_browser_backed_probe_renders_provider_browser_url(self) -> None:
        from cairn.dispatcher.mcp_probe import MCP_PROBE_PATH, run_mcp_probe_request
        from cairn.dispatcher.runtime.process import ProcessResult
        from cairn.shared.config import DispatchConfig

        cfg = DispatchConfig.model_validate(_dispatch_config_payload([
            {
                "id": "js",
                "name": "JS",
                "transport": "stdio",
                "command": "/usr/local/bin/cairn-browser-mcp",
                "args": ["--lease-file", "{capability_root}/leases/js.json", "--", "js-reverse-mcp", "--browserUrl", "{browser_url}"],
                "runtime_provider": {"type": "cloak_sidecar", "resource": "browser_url"},
            },
        ]))

        class _Process:
            def start(self):
                return None

            def communicate(self, timeout):
                return ProcessResult(returncode=0, stdout="initialize + tools/list ok\n", stderr="")

        class _ContainerManager:
            def __init__(self):
                self.writes = {}

            def create_startup_container(self):
                return "probe-container"

            def write_text_file(self, container_name, path, content):
                self.writes[path] = content

            def write_directory(self, *args):
                return None

            def build_exec_process(self, *args, **kwargs):
                return _Process()

            def remove_container(self, *args, **kwargs):
                return None

        class _Cloak:
            def __init__(self):
                self.released = []

            def lease_browser(self, project_id, *, task_instance_id, network_mode):
                return {
                    "browser_url": "http://cairn-cloak-probe:9222",
                    "control_url": "http://cairn-cloak-probe:7310",
                    "lease_id": "lease-1",
                }

            def release_browser(self, *, control_url, lease_id):
                self.released.append((control_url, lease_id))

        manager = _ContainerManager()
        cloak = _Cloak()
        payload = run_mcp_probe_request(
            config=cfg,
            container_manager=manager,
            server_ids=["js"],
            cloak_sidecar_manager=cloak,
        )

        self.assertEqual(payload["results"][0]["status"], "ok")
        written = json.loads(manager.writes[MCP_PROBE_PATH])
        detail = written["mcpServers"]["js"]
        self.assertEqual(detail["args"][-1], "http://cairn-cloak-probe:9222")
        self.assertEqual(detail["env"]["CAIRN_BROWSER_LEASE_ID"], "lease-1")
        self.assertEqual(cloak.released, [("http://cairn-cloak-probe:7310", "lease-1")])

    def test_browser_backed_probe_reports_provider_failure_without_exec(self) -> None:
        from cairn.dispatcher.mcp_probe import run_mcp_probe_request
        from cairn.shared.config import DispatchConfig

        cfg = DispatchConfig.model_validate(_dispatch_config_payload([
            {
                "id": "js",
                "name": "JS",
                "transport": "stdio",
                "command": "/usr/local/bin/cairn-browser-mcp",
                "args": ["js-reverse-mcp", "--browserUrl", "{browser_url}"],
                "runtime_provider": {"type": "cloak_sidecar", "resource": "browser_url"},
            },
        ]))

        class _ContainerManager:
            def __init__(self):
                self.commands = []

            def create_startup_container(self):
                return "probe-container"

            def write_text_file(self, *args):
                return None

            def write_directory(self, *args):
                return None

            def build_exec_process(self, *args, **kwargs):
                self.commands.append(args)
                raise AssertionError("provider failure should skip MCP exec")

            def remove_container(self, *args, **kwargs):
                return None

        payload = run_mcp_probe_request(config=cfg, container_manager=_ContainerManager(), server_ids=["js"])
        self.assertEqual(payload["results"][0]["status"], "error")
        self.assertIn("runtime provider failed", payload["results"][0]["message"])


if __name__ == "__main__":
    unittest.main()
