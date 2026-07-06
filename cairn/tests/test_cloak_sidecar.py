from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class CloakSidecarTests(unittest.TestCase):
    def test_project_uses_cloak_mcp_with_server_assembled_execution_config(self) -> None:
        from cairn.dispatcher.runtime.cloak_sidecar import project_uses_cloak_mcp
        from cairn.server.execution_config import assembler

        header = {
            "settings_json": json.dumps({}),
            "catalog_json": json.dumps([]),
            "role_json": None,
            "dispatch_sha256": "dispatch",
            "resources_sha256": "resources",
            "prompts_sha256": "prompts",
            "prompts_json": None,
            "container_json": json.dumps({}),
            "workers_json": json.dumps([]),
            "version": 1,
        }
        timeout_rows = [
            {"task_type": "bootstrap", "timeout": 5, "conclude_timeout": 5},
            {"task_type": "explore", "timeout": 5, "conclude_timeout": 5},
            {"task_type": "reason", "timeout": 5, "conclude_timeout": None},
        ]
        capability_rows = [
            {
                "task_type": "explore",
                "capabilities_json": json.dumps(
                    {
                        "mcp_server_ids": ["js-reverse-mcp-cloak"],
                        "skill_ids": ["ctf-web-js-analysis"],
                        "user_mcp_server_ids": ["js-reverse-mcp-cloak"],
                        "user_skill_ids": ["ctf-web-js-analysis"],
                        "role_default_skill_ids": [],
                    }
                ),
            }
        ]

        with (
            mock.patch.object(assembler.repository, "get_header", return_value=header),
            mock.patch.object(assembler.repository, "get_timeout_rows", return_value=timeout_rows),
            mock.patch.object(assembler.repository, "get_ai_rows", return_value=[]),
            mock.patch.object(assembler.repository, "get_capability_rows", return_value=capability_rows),
        ):
            config = assembler.load_project_execution_config(None, "proj_001", "explore")

        self.assertTrue(project_uses_cloak_mcp(config))
        self.assertEqual(
            config["capabilities"]["snapshots"][0],
            {"kind": "mcp_server", "capability_id": "js-reverse-mcp-cloak", "source": "selected"},
        )
        self.assertFalse(project_uses_cloak_mcp({
            "capabilities": {"mcp_server_ids": ["js-reverse-mcp-cloak"]},
        }))

    def test_mcp_templates_render_project_values(self) -> None:
        from cairn.dispatcher.capability_mcp import mcp_config_detail
        from cairn.shared.config import McpServerCapabilityConfig

        item = McpServerCapabilityConfig.model_validate(
            {
                "id": "js-reverse-mcp-cloak",
                "name": "JS Reverse",
                "transport": "stdio",
                "command": "/usr/local/bin/js-reverse-mcp-cairn",
                "env": {
                    "CAIRN_PROJECT_ID": "{project_id}",
                    "CAIRN_PROJECT_SAFE_ID": "{project_safe_id}",
                    "CAIRN_TASK_INSTANCE_ID": "{task_instance_id}",
                    "CAIRN_CLOAK_CONTROL_URL": "http://cairn-cloak-{project_safe_id}:7310",
                },
            }
        )

        detail = mcp_config_detail(
            item,
            "/tmp/cap",
            {
                "project_id": "p/1",
                "project_safe_id": "p-1",
                "task_instance_id": "intent-1",
            },
        )

        self.assertEqual(detail["env"]["CAIRN_PROJECT_ID"], "p/1")
        self.assertEqual(detail["env"]["CAIRN_PROJECT_SAFE_ID"], "p-1")
        self.assertEqual(detail["env"]["CAIRN_TASK_INSTANCE_ID"], "intent-1")
        self.assertEqual(detail["env"]["CAIRN_CLOAK_CONTROL_URL"], "http://cairn-cloak-p-1:7310")
        self.assertNotIn("browserUrl", str(detail))

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

    def test_worker_wrapper_leases_runs_and_releases_without_exec(self) -> None:
        wrapper = (_REPO / "container/bin/js-reverse-mcp-cairn").read_text(encoding="utf-8")
        self.assertIn("/lease", wrapper)
        self.assertIn("/release", wrapper)
        self.assertIn("trap release EXIT INT TERM", wrapper)
        self.assertIn('js-reverse-mcp --browserUrl "$browser_url" "$@"', wrapper)
        self.assertNotIn("exec js-reverse-mcp", wrapper)

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
