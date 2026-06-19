from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from helpers import TempYamlConfig

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_DISABLE_DISPATCHER_RELOAD", "1")


class ServerMcpProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def test_single_mcp_probe_success_updates_yaml(self) -> None:
        from cairn.server.routers.capabilities import (
            get_capability_catalog,
            probe_admin_capability,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

        upsert_admin_capability("mcp_server", "stdio-mcp", CapabilityAdminRequest(
            id="stdio-mcp",
            name="Stdio MCP",
            task_types=["bootstrap"],
            transport="stdio",
            command="stdio-mcp",
        ))
        response = MagicMock()
        response.read.return_value = json.dumps({
            "results": [
                {"capability_id": "stdio-mcp", "status": "ok", "message": "initialize + tools/list ok"}
            ]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            entry = probe_admin_capability("mcp_server", "stdio-mcp")

        self.assertEqual(entry.status, "ok")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:9100/mcp-probe")
        self.assertTrue(request.headers["Authorization"].startswith("Bearer "))
        item = next(item for item in get_capability_catalog() if item.id == "stdio-mcp")
        self.assertTrue(item.available)
        self.assertEqual(item.last_probe_status, "ok")
        self.assertEqual(item.last_probe_message, "initialize + tools/list ok")

    def test_dispatcher_unreachable_marks_mcp_error(self) -> None:
        from cairn.server.routers.capabilities import (
            get_capability_catalog,
            probe_admin_capability,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

        upsert_admin_capability("mcp_server", "offline-mcp", CapabilityAdminRequest(
            id="offline-mcp",
            name="Offline MCP",
            task_types=["bootstrap"],
            transport="stdio",
            command="offline-mcp",
        ))

        with patch("urllib.request.urlopen", side_effect=OSError("dispatcher down")):
            entry = probe_admin_capability("mcp_server", "offline-mcp")

        self.assertEqual(entry.status, "error")
        self.assertIn("dispatcher probe failed", entry.message)
        item = next(item for item in get_capability_catalog() if item.id == "offline-mcp")
        self.assertFalse(item.available)
        self.assertEqual(item.last_probe_status, "error")

    def test_probe_all_updates_partial_results(self) -> None:
        from cairn.server.routers.capabilities import (
            get_capability_catalog,
            probe_all_admin_mcp_servers,
            upsert_admin_capability,
        )
        from cairn.server.schemas import CapabilityAdminRequest

        for capability_id in ("a-mcp", "b-mcp"):
            upsert_admin_capability("mcp_server", capability_id, CapabilityAdminRequest(
                id=capability_id,
                name=capability_id,
                task_types=["bootstrap"],
                transport="stdio",
                command=capability_id,
            ))
        response = MagicMock()
        response.read.return_value = json.dumps({
            "results": [
                {"capability_id": "a-mcp", "status": "ok", "message": "ready"},
                {"capability_id": "b-mcp", "status": "error", "message": "boom"},
            ]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            results = probe_all_admin_mcp_servers()

        by_id = {item.capability_id: item for item in results}
        self.assertEqual(by_id["a-mcp"].status, "ok")
        self.assertEqual(by_id["b-mcp"].status, "error")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data.decode("utf-8"))["server_ids"], ["a-mcp", "b-mcp"])
        items = {item.id: item for item in get_capability_catalog() if item.kind == "mcp_server"}
        self.assertTrue(items["a-mcp"].available)
        self.assertFalse(items["b-mcp"].available)


if __name__ == "__main__":
    unittest.main()
