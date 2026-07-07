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

    def test_tool_sidecar_create_uses_expected_name_labels_network_and_mount(self) -> None:
        import cairn.dispatcher.runtime.tool_sidecar as tool_mod
        from cairn.dispatcher.runtime.tool_sidecar import ToolSidecarManager
        from cairn.shared.config import ToolSidecarsConfig

        client = mock.Mock()
        client.containers.get.side_effect = tool_mod.NotFound("not found")
        config = ToolSidecarsConfig.model_validate(
            {
                "kali": {
                    "image": "cairn-kali-tools:latest",
                    "network_mode": "cairn",
                    "enabled": True,
                    "user": "kali",
                    "exec_user": "kali",
                    "cap_add": ["NET_RAW"],
                    "bind_mounts": [
                        {
                            "name": "project-files",
                            "host_path": str(_REPO / "datas" / "project-files" / "{project_id}"),
                            "container_path": "/home/kali/workspace",
                            "read_only": False,
                        }
                    ],
                }
            }
        )
        manager = ToolSidecarManager(config, client=client)
        with (
            mock.patch.object(manager, "status", side_effect=[
                mock.Mock(running=False),
                mock.Mock(running=True),
            ]),
            mock.patch.object(manager._preflight, "run") as preflight,
        ):
            manager.ensure_running("proj/1", "kali")

        kwargs = client.containers.run.call_args.kwargs
        args = client.containers.run.call_args.args
        self.assertEqual(args[0], "cairn-kali-tools:latest")
        self.assertEqual(args[1], ["/usr/local/bin/kali-mcp-http-sidecar"])
        self.assertEqual(kwargs["name"], "cairn-kali-proj-1")
        self.assertEqual(kwargs["network_mode"], "cairn")
        self.assertEqual(kwargs["labels"]["cairn.managed"], "true")
        self.assertEqual(kwargs["labels"]["cairn.kind"], "tool-sidecar")
        self.assertEqual(kwargs["labels"]["cairn.tool"], "kali")
        self.assertEqual(kwargs["labels"]["cairn.project_id"], "proj/1")
        self.assertEqual(kwargs["user"], "kali")
        self.assertEqual(kwargs["cap_add"], ["NET_RAW"])
        volume = next(iter(kwargs["volumes"].values()))
        self.assertEqual(volume, {"bind": "/home/kali/workspace", "mode": "rw"})
        preflight.assert_called_once()

    def test_sidecar_status_merges_health_ready_state_and_errors(self) -> None:
        import cairn.dispatcher.runtime.cloak_sidecar as cloak_mod
        from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager
        from cairn.shared.config import CloakSidecarConfig

        container = mock.Mock()
        container.attrs = {
            "State": {"Status": "running"},
            "NetworkSettings": {"Ports": {"6080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "16080"}]}},
        }
        client = mock.Mock()
        client.containers.get.return_value = container
        config = CloakSidecarConfig.model_validate(
            {
                "image": "cairn-cloak-browser:js-reverse",
                "slots": 2,
                "novnc": {"enabled": True, "host": "127.0.0.1"},
                "profile_root": str(_REPO / "datas" / "cloak-profiles-test"),
            }
        )
        response = mock.Mock()
        response.json.return_value = {
            "ready": True,
            "state": "ready",
            "slots": [
                {"slot": 0, "busy": True, "ready": True, "error": ""},
                {"slot": 1, "busy": False, "ready": False, "error": "launch failed"},
            ],
        }

        with mock.patch.object(cloak_mod.requests, "get", return_value=response) as get:
            status = CloakSidecarManager(config, client=client).status("proj/1")

        self.assertEqual(get.call_args.kwargs["proxies"], cloak_mod.CLOAK_CONTROL_NO_PROXIES)
        self.assertTrue(status.running)
        self.assertTrue(status.ready)
        self.assertEqual(status.state, "ready")
        self.assertEqual(status.slots, 2)
        self.assertEqual(status.busy_slots, 1)
        self.assertEqual(status.error, "slot 1: launch failed")
        self.assertEqual(status.model_dump()["ready"], True)
        self.assertEqual(status.model_dump()["state"], "ready")

    def test_ensure_running_waits_for_control_service(self) -> None:
        import cairn.dispatcher.runtime.cloak_sidecar as cloak_mod
        from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager, CloakSidecarStatus
        from cairn.shared.config import CloakSidecarConfig

        client = mock.Mock()
        client.containers.get.side_effect = cloak_mod.NotFound("not found")
        config = CloakSidecarConfig.model_validate(
            {
                "image": "cairn-cloak-browser:js-reverse",
                "slots": 2,
                "novnc": {"enabled": False, "host": "127.0.0.1"},
                "profile_root": str(_REPO / "datas" / "cloak-profiles-test"),
            }
        )
        manager = CloakSidecarManager(config, client=client)
        waiting = CloakSidecarStatus("proj/1", "cairn-cloak-proj-1", running=True, enabled=True, state="running", error="health unavailable: refused")
        ready = CloakSidecarStatus("proj/1", "cairn-cloak-proj-1", running=True, enabled=True, ready=False, state="launching")

        with (
            mock.patch.object(manager, "status", side_effect=[
                CloakSidecarStatus("proj/1", "cairn-cloak-proj-1", running=False, enabled=True),
                waiting,
                ready,
            ]) as status,
            mock.patch.object(cloak_mod.time, "sleep"),
        ):
            result = manager.ensure_running("proj/1", network_mode="cairn")

        self.assertIs(result, ready)
        self.assertEqual(status.call_count, 3)

    def test_lease_browser_reports_control_service_unavailable(self) -> None:
        import cairn.dispatcher.runtime.cloak_sidecar as cloak_mod
        from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager, CloakSidecarStatus
        from cairn.shared.config import CloakSidecarConfig

        config = CloakSidecarConfig.model_validate(
            {
                "image": "cairn-cloak-browser:js-reverse",
                "slots": 1,
                "novnc": {"enabled": False, "host": "127.0.0.1"},
                "profile_root": str(_REPO / "datas" / "cloak-profiles-test"),
            }
        )
        manager = CloakSidecarManager(config, client=mock.Mock())
        running = CloakSidecarStatus("proj/1", "cairn-cloak-proj-1", running=True, enabled=True, state="running")
        unavailable = CloakSidecarStatus(
            "proj/1",
            "cairn-cloak-proj-1",
            running=True,
            enabled=True,
            state="running",
            error="health unavailable: HTTPConnectionPool(host='cairn-cloak-proj-1', port=7310)",
        )

        with (
            mock.patch.object(manager, "ensure_running", return_value=running),
            mock.patch.object(manager, "_wait_for_browser_slot", return_value=unavailable),
            mock.patch.object(cloak_mod.requests, "post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "control service unavailable"):
                manager.lease_browser("proj/1", task_instance_id="intent-1", network_mode="cairn")

        post.assert_not_called()

    def test_lease_browser_disables_environment_proxies_for_control_request(self) -> None:
        import cairn.dispatcher.runtime.cloak_sidecar as cloak_mod
        from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager, CloakSidecarStatus
        from cairn.shared.config import CloakSidecarConfig

        config = CloakSidecarConfig.model_validate(
            {
                "image": "cairn-cloak-browser:js-reverse",
                "slots": 1,
                "novnc": {"enabled": False, "host": "127.0.0.1"},
                "profile_root": str(_REPO / "datas" / "cloak-profiles-test"),
            }
        )
        manager = CloakSidecarManager(config, client=mock.Mock())
        ready = CloakSidecarStatus("proj/1", "cairn-cloak-proj-1", running=True, enabled=True, ready=True, state="ready")
        response = mock.Mock()
        response.json.return_value = {"browser_url": "http://cairn-cloak-proj-1:9222", "lease_id": "lease-1"}

        with (
            mock.patch.object(manager, "ensure_running", return_value=ready),
            mock.patch.object(manager, "_wait_for_browser_slot", return_value=ready),
            mock.patch.object(cloak_mod.requests, "post", return_value=response) as post,
        ):
            lease = manager.lease_browser("proj/1", task_instance_id="intent-1", network_mode="cairn")

        self.assertEqual(lease["browser_url"], "http://cairn-cloak-proj-1:9222")
        self.assertEqual(post.call_args.kwargs["proxies"], cloak_mod.CLOAK_CONTROL_NO_PROXIES)

    def test_lease_browser_waits_for_launching_browser_slot(self) -> None:
        import cairn.dispatcher.runtime.cloak_sidecar as cloak_mod
        from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager, CloakSidecarStatus
        from cairn.shared.config import CloakSidecarConfig

        config = CloakSidecarConfig.model_validate(
            {
                "image": "cairn-cloak-browser:js-reverse",
                "slots": 1,
                "novnc": {"enabled": False, "host": "127.0.0.1"},
                "profile_root": str(_REPO / "datas" / "cloak-profiles-test"),
            }
        )
        manager = CloakSidecarManager(config, client=mock.Mock())
        launching = CloakSidecarStatus(
            "proj/1",
            "cairn-cloak-proj-1",
            running=True,
            enabled=True,
            ready=False,
            state="launching",
        )
        ready = CloakSidecarStatus(
            "proj/1",
            "cairn-cloak-proj-1",
            running=True,
            enabled=True,
            ready=True,
            state="ready",
        )

        with (
            mock.patch.object(manager, "_wait_for_control_service", return_value=launching),
            mock.patch.object(manager, "status", side_effect=[ready]) as status,
            mock.patch.object(cloak_mod.time, "sleep") as sleep,
        ):
            result = manager._wait_for_browser_slot("proj/1", "cairn-cloak-proj-1")

        self.assertIs(result, ready)
        sleep.assert_called_once()
        status.assert_called_once_with("proj/1")

    def test_control_server_listens_before_launching_slots(self) -> None:
        sidecar = (_REPO / "capabilities/mcp/js-reverse-mcp/sidecar/control-server.mjs").read_text(encoding="utf-8")

        self.assertLess(sidecar.index("server.listen(controlPort"), sidecar.index("launchAll().catch"))
        self.assertNotIn("await launchAll();", sidecar)
        self.assertIn("ready,", sidecar)
        self.assertIn("state: stateName", sidecar)
        self.assertIn("launching,", sidecar)

    def test_control_server_launch_completion_drains_waiters(self) -> None:
        sidecar = (_REPO / "capabilities/mcp/js-reverse-mcp/sidecar/control-server.mjs").read_text(encoding="utf-8")

        self.assertIn("finally {\n      drainWaiters();\n    }", sidecar)
        self.assertIn("if (!isLaunching() && !hasUsableBrowser())", sidecar)

    def test_control_server_removes_stale_chromium_profile_locks(self) -> None:
        sidecar = (_REPO / "capabilities/mcp/js-reverse-mcp/sidecar/control-server.mjs").read_text(encoding="utf-8")

        self.assertIn("function removeStaleProfileLocks(userDataDir)", sidecar)
        self.assertIn("'SingletonLock', 'SingletonSocket', 'SingletonCookie'", sidecar)
        self.assertLess(sidecar.index("removeStaleProfileLocks(userDataDir)"), sidecar.index("launchPersistentContext({"))
        self.assertIn("env: process.env", sidecar)

    def test_sidecar_entrypoint_waits_for_xvfb_before_control_server(self) -> None:
        entrypoint = (_REPO / "capabilities/mcp/js-reverse-mcp/sidecar/entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("Xvfb \"$DISPLAY\" -screen 0 1440x1000x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &", entrypoint)
        self.assertIn('display_socket="/tmp/.X11-unix/X${display_number}"', entrypoint)
        self.assertIn('if [ -S "$display_socket" ]; then', entrypoint)
        self.assertIn("Xvfb did not create ${display_socket}", entrypoint)
        self.assertLess(entrypoint.index('if [ ! -S "$display_socket" ]'), entrypoint.index("fluxbox >/tmp/fluxbox.log"))
        self.assertLess(entrypoint.index('if [ ! -S "$display_socket" ]'), entrypoint.index("exec node /opt/cairn-cloak/control-server.mjs"))

    def test_frontend_button_precedes_fact_intent_counts(self) -> None:
        html = (_REPO / "cairn/src/cairn/server/partials/view_graph.html").read_text(encoding="utf-8")
        cloak_index = html.index("Cloak UI")
        fact_index = html.index("`${projectFactCount()} facts`")
        intent_index = html.index("`${projectIntentCount()} intents`")
        self.assertLess(cloak_index, fact_index)
        self.assertLess(fact_index, intent_index)

    def test_browser_mcp_wrapper_releases_without_leasing(self) -> None:
        wrapper = (_REPO / "container/runner/bin/cairn-browser-mcp").read_text(encoding="utf-8")
        compat = (_REPO / "container/runner/bin/js-reverse-mcp-cairn").read_text(encoding="utf-8")
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
        self.assertIn("node node_modules/cloakbrowser/dist/cli.js install", dockerfile)
        self.assertIn("CloakBrowser binary missing after install", dockerfile)
        self.assertIn("EXPOSE 6080 7310 9222 9223", dockerfile)

    def test_start_script_preloads_cloak_browser_archive(self) -> None:
        start_script = (_REPO / "start.sh").read_text(encoding="utf-8")

        self.assertIn("prepare_cloak_browser_archive", start_script)
        self.assertIn("146.0.7680.177.5", start_script)
        self.assertIn("cloakbrowser-linux-x64.tar.gz", start_script)
        self.assertIn("capabilities/mcp/js-reverse-mcp/sidecar/.cloak-downloads", start_script)
        self.assertIn("https://cloakbrowser.dev/${cloak_release}", start_script)
        self.assertIn("https://github.com/CloakHQ/cloakbrowser/releases/download/${cloak_release}", start_script)
        self.assertIn('download_cloak_file "SHA256SUMS"', start_script)
        self.assertIn('download_cloak_file "SHA256SUMS.sig"', start_script)
        self.assertIn("curl -fL --retry 3", start_script)
        self.assertIn("sha256sum", start_script)
        self.assertIn("shasum -a 256", start_script)
        self.assertLess(start_script.index("prepare_cloak_browser_archive\n"), start_script.index("exec docker compose up"))

    def test_sidecar_dockerfile_prefers_local_cloak_archive_with_online_fallback(self) -> None:
        dockerfile = (_REPO / "capabilities/mcp/js-reverse-mcp/sidecar/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY .cloak-downloads /opt/cairn-cloak/.cloak-downloads", dockerfile)
        self.assertIn("COPY install-local-cloak.mjs /opt/cairn-cloak/install-local-cloak.mjs", dockerfile)
        self.assertIn("node install-local-cloak.mjs", dockerfile)
        self.assertIn('if [ "$status" -eq 42 ]', dockerfile)
        self.assertIn("node node_modules/cloakbrowser/dist/cli.js install", dockerfile)
        self.assertLess(dockerfile.index("node install-local-cloak.mjs"), dockerfile.index("node node_modules/cloakbrowser/dist/cli.js install"))

    def test_local_cloak_installer_verifies_hash_and_binary_path(self) -> None:
        installer = (_REPO / "capabilities/mcp/js-reverse-mcp/sidecar/install-local-cloak.mjs").read_text(encoding="utf-8")

        self.assertIn("LOCAL_ARCHIVE_MISSING_EXIT_CODE = 42", installer)
        self.assertIn("getChromiumVersion", installer)
        self.assertIn("getArchiveName", installer)
        self.assertIn("getBinaryDir(version)", installer)
        self.assertIn("getBinaryPath(version)", installer)
        self.assertIn("SHA256SUMS", installer)
        self.assertIn("createHash('sha256')", installer)
        self.assertIn("tarExtract", installer)
        self.assertIn("flattenSingleSubdir(binaryDir)", installer)
        self.assertIn("fs.chmodSync(binaryPath, 0o755)", installer)
        self.assertIn("CloakBrowser binary missing after local archive install", installer)


if __name__ == "__main__":
    unittest.main()
