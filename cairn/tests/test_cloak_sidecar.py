from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class CloakSidecarTests(unittest.TestCase):
    def test_browser_runtime_provider_renders_browser_url_and_release_env(self) -> None:
        from cairn.dispatcher.capability_mcp import mcp_config_detail
        from cairn.dispatcher.runtime.browser_provider import BrowserRuntimeLease
        from cairn.shared.config import McpServerCapabilityConfig

        item = McpServerCapabilityConfig.model_validate(
            {
                "id": "js-reverse-mcp-cloak",
                "name": "JS Reverse",
                "transport": "stdio",
                "command": "/usr/local/bin/cairn-browser-mcp",
                "args": ["--lease-file", "{capability_root}/leases/js-reverse-mcp-cloak.json", "--", "js-reverse-mcp", "--browserUrl", "{browser_url}"],
                "runtime_provider": {"type": "cloak_sidecar", "resource": "browser_url"},
            }
        )
        lease = BrowserRuntimeLease(
            browser_url="http://cairn-cloak-p-1:9222",
            release_env={
                "CAIRN_BROWSER_LEASE_FILE": "/tmp/cap/leases/js-reverse-mcp-cloak.json",
                "CAIRN_BROWSER_LEASE_CONTROL_URL": "http://cairn-cloak-p-1:7310",
                "CAIRN_BROWSER_LEASE_ID": "intent-1",
            },
            lease_payload={},
        )

        detail = mcp_config_detail(
            item,
            "/tmp/cap",
            {
                "project_id": "p/1",
                "project_safe_id": "p-1",
                "task_instance_id": "intent-1",
            },
            {"js-reverse-mcp-cloak": lease},
        )

        self.assertEqual(detail["command"], "/usr/local/bin/cairn-browser-mcp")
        self.assertIn("http://cairn-cloak-p-1:9222", detail["args"])
        self.assertEqual(detail["args"][1], "/tmp/cap/leases/js-reverse-mcp-cloak.json")
        self.assertEqual(detail["env"]["CAIRN_BROWSER_LEASE_ID"], "intent-1")
        self.assertNotIn("CAIRN_CLOAK_CONTROL_URL", detail["env"])

    def test_sidecar_create_uses_labels_network_mount_and_novnc_port(self) -> None:
        import cairn.dispatcher.runtime.cloak_sidecar as cloak_mod
        from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager
        from cairn.shared.config import CloakSidecarConfig

        client = mock.Mock()
        client.containers.get.side_effect = cloak_mod.NotFound("not found")
        config = CloakSidecarConfig.model_validate(
            {
                "image": "cairn-cloak-browser:js-reverse",
                "slots": 2,
                "novnc": {"enabled": True, "host": "127.0.0.1"},
                "profile_root": str(_REPO / "datas" / "cloak-profiles-test"),
            }
        )
        manager = CloakSidecarManager(config, client=client)
        with mock.patch.object(manager, "status") as status:
            status.side_effect = [
                mock.Mock(running=False),
                mock.Mock(running=True),
            ]
            manager.ensure_running("proj/1", network_mode="cairn")

        kwargs = client.containers.run.call_args.kwargs
        self.assertEqual(kwargs["name"], "cairn-cloak-proj-1")
        self.assertEqual(kwargs["network_mode"], "cairn")
        self.assertEqual(kwargs["labels"]["cairn.managed"], "true")
        self.assertEqual(kwargs["labels"]["cairn.cloak_sidecar"], "true")
        self.assertEqual(kwargs["labels"]["cairn.project_id"], "proj/1")
        self.assertEqual(kwargs["environment"]["CAIRN_CLOAK_SLOTS"], "2")
        self.assertEqual(kwargs["ports"], {"6080/tcp": ("127.0.0.1", None)})
        volume = next(iter(kwargs["volumes"].values()))
        self.assertEqual(volume, {"bind": "/profiles", "mode": "rw"})

    def test_frontend_button_precedes_fact_intent_counts(self) -> None:
        html = (_REPO / "cairn/src/cairn/server/partials/view_graph.html").read_text(encoding="utf-8")
        cloak_index = html.index("Cloak UI")
        fact_index = html.index("`${projectFactCount()} facts`")
        intent_index = html.index("`${projectIntentCount()} intents`")
        self.assertLess(cloak_index, fact_index)
        self.assertLess(fact_index, intent_index)

    def test_browser_mcp_wrapper_releases_without_leasing(self) -> None:
        wrapper = (_REPO / "container/bin/cairn-browser-mcp").read_text(encoding="utf-8")
        compat = (_REPO / "container/bin/js-reverse-mcp-cairn").read_text(encoding="utf-8")
        self.assertNotIn("/lease", wrapper)
        self.assertIn("/release", wrapper)
        self.assertIn("trap release EXIT INT TERM", wrapper)
        self.assertIn('"$@"', wrapper)
        self.assertIn("cairn-browser-mcp", compat)

    def test_sidecar_dockerfile_pins_versions_and_exposes_novnc(self) -> None:
        dockerfile = (_REPO / "capabilities/mcp/js-reverse-mcp/sidecar/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("http://mirrors.ustc.edu.cn/debian", dockerfile)
        self.assertIn("http://mirrors.ustc.edu.cn/debian-security", dockerfile)
        self.assertIn("https://mirrors.ustc.edu.cn", dockerfile)
        self.assertIn("sed -i 's|http://mirrors.ustc.edu.cn|https://mirrors.ustc.edu.cn|g'", dockerfile)
        self.assertLess(dockerfile.index("mirrors.ustc.edu.cn/debian"), dockerfile.index("apt-get update"))
        self.assertLess(dockerfile.index("ca-certificates"), dockerfile.index("sed -i"))
        self.assertIn("cloakbrowser@0.4.8", dockerfile)
        self.assertIn("npx cloakbrowser install", dockerfile)
        self.assertIn("EXPOSE 6080 7310 9222 9223", dockerfile)


if __name__ == "__main__":
    unittest.main()
