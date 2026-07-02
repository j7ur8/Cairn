"""Tests for the ``container.user`` field.

Background: on macOS Docker Desktop, the worker container (running as
``kali`` = UID 1000) cannot write to a host bind mount that is owned by a
different UID. The fix is to let the operator configure ``container.user``
to match the host user's ``uid:gid`` and pass it through to
``docker.containers.run``.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Schema: ContainerConfig.user
# ---------------------------------------------------------------------------


class _ContainerConfigHarness:
    """Build a ContainerConfig with a minimal but valid bind_mounts list."""

    @staticmethod
    def _build(user=None):
        from cairn.shared.config import BindMountConfig, ContainerConfig

        return ContainerConfig(
            image="cairn/test:latest",
            user=user,
            network_mode="cairn",
            completed_action="stop",
            bind_mounts=[
                BindMountConfig(
                    name="project-files",
                    host_path="./datas/project-files/{project_id}",
                    container_path="/home/kali/workspace",
                    read_only=False,
                ),
            ],
        )


class ContainerConfigUserSchemaTests(unittest.TestCase, _ContainerConfigHarness):
    def test_default_user_is_none(self):
        cfg = self._build()
        self.assertIsNone(cfg.user)

    def test_explicit_none_is_none(self):
        cfg = self._build(user=None)
        self.assertIsNone(cfg.user)

    def test_uid_gid_string_accepted(self):
        cfg = self._build(user="501:20")
        self.assertEqual(cfg.user, "501:20")

    def test_root_uid_accepted(self):
        # On macOS Docker Desktop, VirtioFS only honours writes from root, so
        # "0:0" is the recommended value there. The schema must accept it.
        cfg = self._build(user="0:0")
        self.assertEqual(cfg.user, "0:0")

    def test_uid_only_string_accepted(self):
        # Pass-through to docker; docker accepts "uid" or "uid:gid".
        cfg = self._build(user="1000")
        self.assertEqual(cfg.user, "1000")

    def test_empty_string_rejected(self):
        from cairn.shared.config import BindMountConfig, ContainerConfig

        with self.assertRaises(ValidationError):
            ContainerConfig(
                image="cairn/test:latest",
                user="",
                network_mode="cairn",
                completed_action="stop",
                bind_mounts=[
                    BindMountConfig(
                        name="x",
                        host_path="./x",
                        container_path="/mnt/x",
                        read_only=False,
                    ),
                ],
            )


# ---------------------------------------------------------------------------
# Runtime: ContainerManager passes user= to docker.containers.run
# ---------------------------------------------------------------------------


class _DockerMock:
    """Minimal stand-in for ``docker.from_env()`` that records kwargs.

    ``containers.get`` is configured to raise ``NotFound`` so
    ``ContainerManager._get_container`` returns ``None`` — this makes
    ``ensure_running`` reach the ``containers.run`` branch on a fresh project.
    """

    def __init__(self):
        from docker.errors import NotFound

        self.client = MagicMock()
        self.containers = MagicMock()
        self.client.containers = self.containers
        container = MagicMock()
        container.exec_run.return_value = type("R", (), {"exit_code": 0, "output": b""})()
        self.created_container = container
        self._created = False
        self.containers.get.side_effect = self._get
        self.containers.run.side_effect = self._run

    def install(self):
        return patch("docker.from_env", return_value=self.client)

    def _get(self, _name):
        from docker.errors import NotFound

        if self._created:
            return self.created_container
        raise NotFound("not found")

    def _run(self, *args, **kwargs):
        self._created = True
        return self.created_container


class _ListedContainer:
    def __init__(self, name: str, labels: dict[str, str] | None = None):
        self.name = name
        self.labels = labels or {}


class _ExistingContainer:
    def __init__(self, *, source: str, rw: bool, status: str = "running", image: str | None = None) -> None:
        self.attrs = {
            "Config": {"Image": image} if image is not None else {},
            "State": {"Status": status},
            "Mounts": [
                {
                    "Destination": "/home/kali/workspace",
                    "Source": source,
                    "RW": rw,
                }
            ],
        }
        self.reload = MagicMock()
        self.remove = MagicMock()
        self.start = MagicMock()


class ContainerUserRuntimeTests(unittest.TestCase):
    def _make_manager(self, user, exec_user=None):
        from cairn.dispatcher.runtime.containers import ContainerManager
        from cairn.shared.config import BindMountConfig, ContainerConfig

        cfg = ContainerConfig(
            image="cairn/test:latest",
            user=user,
            exec_user=exec_user,
            network_mode="cairn",
            completed_action="stop",
            bind_mounts=[
                BindMountConfig(
                    name="project-files",
                    host_path="./datas/project-files/{project_id}",
                    container_path="/home/kali/workspace",
                    read_only=False,
                ),
            ],
        )
        return ContainerManager(cfg)

    def test_user_none_passes_user_none(self):
        # Docker treats ``user=None`` as "use the image USER directive" — the
        # same effective behavior as omitting the kwarg.
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user=None)
            mgr.ensure_running("proj-1")

        self.assertEqual(dm.containers.run.call_count, 1)
        kwargs = dm.containers.run.call_args.kwargs
        self.assertIn("user", kwargs)
        self.assertIsNone(kwargs["user"])

    def test_user_string_is_passed_through(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="501:20")
            mgr.ensure_running("proj-1")

        self.assertEqual(dm.containers.run.call_count, 1)
        kwargs = dm.containers.run.call_args.kwargs
        self.assertEqual(kwargs.get("user"), "501:20")

    def test_container_name_uses_project_id(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="0:0")

        self.assertEqual(mgr.container_name("proj-1"), "cairn-worker-proj-1")

    def test_created_container_receives_owner_labels(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="0:0")
            mgr.ensure_running("proj-1")

        kwargs = dm.containers.run.call_args.kwargs
        self.assertEqual(kwargs["labels"]["cairn.managed"], "true")
        self.assertEqual(kwargs["labels"]["cairn.project_id"], "proj-1")
        self.assertEqual(kwargs["labels"]["cairn.startup_healthcheck"], "false")

    def test_project_workspace_preflight_runs_root_setup_and_kali_probe(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="0:0", exec_user="kali")
            mgr.ensure_running("proj-1")

        exec_calls = dm.created_container.exec_run.call_args_list
        self.assertEqual(len(exec_calls), 2)
        self.assertEqual(exec_calls[0].kwargs.get("user"), "0:0")
        self.assertEqual(exec_calls[1].kwargs.get("user"), "kali")
        setup_argv = exec_calls[0].args[0]
        probe_argv = exec_calls[1].args[0]
        self.assertIn("/home/kali/workspace", setup_argv)
        self.assertIn("/home/kali/workspace", probe_argv)
        self.assertIn("reports/ctf-web-js-analysis", setup_argv[2])

    def test_startup_container_also_receives_user(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="501:20")
            name = mgr.create_startup_container()

        self.assertEqual(dm.containers.run.call_count, 1)
        kwargs = dm.containers.run.call_args.kwargs
        self.assertEqual(name, "cairn-worker-startup-healthcheck")
        self.assertEqual(kwargs["name"], "cairn-worker-startup-healthcheck")
        self.assertEqual(kwargs.get("user"), "501:20")

    def test_startup_container_removes_stale_container_before_create(self):
        dm = _DockerMock()
        stale = MagicMock()
        dm.containers.get.side_effect = [stale]
        with dm.install():
            mgr = self._make_manager(user="0:0")
            mgr.create_startup_container()

        stale.remove.assert_called_once_with(force=True)
        self.assertEqual(dm.containers.run.call_count, 1)

    def test_existing_running_container_with_mount_source_drift_is_recreated(self):
        dm = _DockerMock()
        stale = _ExistingContainer(source="/tmp/old-project-files/proj-1", rw=True, status="running")
        dm.containers.get.side_effect = [stale, stale, stale, stale, dm.created_container]
        with dm.install():
            mgr = self._make_manager(user="0:0")
            name = mgr.ensure_running("proj-1")

        self.assertEqual(name, "cairn-worker-proj-1")
        stale.remove.assert_called_once_with(force=True)
        self.assertEqual(dm.containers.run.call_count, 1)
        self.assertIn("proj-1", next(iter(dm.containers.run.call_args.kwargs["volumes"])))

    def test_existing_stopped_container_with_mount_mode_drift_is_recreated(self):
        dm = _DockerMock()
        expected_source = str((Path("./datas/project-files/proj-1")).expanduser().resolve(strict=False))
        stale = _ExistingContainer(source=expected_source, rw=False, status="exited")
        dm.containers.get.side_effect = [stale, stale, stale, stale, dm.created_container]
        with dm.install():
            mgr = self._make_manager(user="0:0")
            mgr.ensure_running("proj-1")

        stale.remove.assert_called_once_with(force=True)
        stale.start.assert_not_called()
        self.assertEqual(dm.containers.run.call_count, 1)

    def test_existing_running_container_without_mount_drift_is_reused(self):
        dm = _DockerMock()
        expected_source = str((Path("./datas/project-files/proj-1")).expanduser().resolve(strict=False))
        existing = _ExistingContainer(source=expected_source, rw=True, status="running")
        dm.containers.get.side_effect = [existing, existing, existing]
        existing.exec_run = MagicMock(return_value=type("R", (), {"exit_code": 0, "output": b""})())
        with dm.install():
            mgr = self._make_manager(user="0:0")
            name = mgr.ensure_running("proj-1")

        self.assertEqual(name, "cairn-worker-proj-1")
        existing.remove.assert_not_called()
        existing.start.assert_not_called()
        dm.containers.run.assert_not_called()

    def test_existing_running_container_with_image_drift_is_recreated(self):
        dm = _DockerMock()
        expected_source = str((Path("./datas/project-files/proj-1")).expanduser().resolve(strict=False))
        stale = _ExistingContainer(
            source=expected_source,
            rw=True,
            status="running",
            image="cairn/old:latest",
        )
        dm.containers.get.side_effect = [stale, stale, stale, stale, dm.created_container]
        with dm.install():
            mgr = self._make_manager(user="0:0")
            mgr.ensure_running("proj-1")

        stale.remove.assert_called_once_with(force=True)
        self.assertEqual(dm.containers.run.call_count, 1)
        self.assertEqual(dm.containers.run.call_args.args[0], "cairn/test:latest")

    def test_existing_container_inspection_error_is_logged_without_recreate(self):
        from cairn.dispatcher.runtime.container_lifecycle import ContainerLifecycle
        from cairn.shared.config import BindMountConfig, ContainerConfig

        lifecycle = ContainerLifecycle(
            config=ContainerConfig(
                image="cairn/test:latest",
                user="0:0",
                network_mode="cairn",
                completed_action="stop",
                bind_mounts=[
                    BindMountConfig(
                        name="project-files",
                        host_path="./datas/project-files/{project_id}",
                        container_path="/home/kali/workspace",
                        read_only=False,
                    ),
                ],
            ),
            access=MagicMock(),
            api_error_type=Exception,
            docker_exception_type=Exception,
            proxy_environment=lambda _project_id: {},
            inspect_state=lambda _name: "running",
            log_mount_mismatches=MagicMock(),
            mount_mismatches=lambda _name, _project_id: ["failed to inspect mounts: unavailable"],
        )
        lifecycle.remove_container = MagicMock()
        lifecycle._create_container = MagicMock(return_value="created")  # type: ignore[method-assign]

        result = lifecycle.ensure_running("proj-1")

        self.assertEqual(result, "cairn-worker-proj-1")
        lifecycle.remove_container.assert_not_called()
        lifecycle._create_container.assert_not_called()

    def test_startup_container_receives_owner_labels(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="0:0")
            mgr.create_startup_container()

        kwargs = dm.containers.run.call_args.kwargs
        self.assertEqual(kwargs["labels"]["cairn.project_id"], "startup-healthcheck")
        self.assertEqual(kwargs["labels"]["cairn.startup_healthcheck"], "true")

    def test_managed_container_names_filters_managed_label(self):
        dm = _DockerMock()
        dm.containers.list.return_value = [
            _ListedContainer("cairn-worker-proj-1"),
            _ListedContainer("cairn-worker-startup-healthcheck"),
            _ListedContainer("cairn-worker-startup-by-label", {"cairn.startup_healthcheck": "true"}),
        ]
        with dm.install():
            mgr = self._make_manager(user="0:0")
            names = mgr.managed_container_names()

        self.assertEqual(names, ["cairn-worker-proj-1"])
        dm.containers.list.assert_called_once_with(
            all=True,
            filters={
                "label": [
                    "cairn.managed=true",
                ],
            },
        )

    def test_exec_user_is_passed_to_managed_process(self):
        dm = _DockerMock()
        container = MagicMock()
        container.client.api = MagicMock()
        with dm.install():
            mgr = self._make_manager(user="0:0", exec_user="kali")
            with patch.object(mgr, "_require_container", return_value=container):
                process = mgr.build_exec_process("c", {}, ["echo", "ok"])

        self.assertEqual(process.user, "kali")

    def test_tty_is_passed_to_managed_process(self):
        dm = _DockerMock()
        container = MagicMock()
        container.client.api = MagicMock()
        with dm.install():
            mgr = self._make_manager(user="0:0")
            with patch.object(mgr, "_require_container", return_value=container):
                process = mgr.build_exec_process("c", {}, ["echo", "ok"], tty=True)

        self.assertTrue(process.tty)


# ---------------------------------------------------------------------------
# host_path env interpolation in config.yaml
# ---------------------------------------------------------------------------


_BIND_MOUNT_INTERPOLATION_YAML_TEMPLATE = """\
server:
  base_url: "http://127.0.0.1:8000"
  database:
    url: postgresql+psycopg://cairn:cairn@localhost:5432/cairn
  auth:
    jwt_secret: test-jwt-secret-do-not-use-in-prod-32bytes
    dispatcher_api_token: test-dispatcher-token
  paths:
    datas_root: "$HOST_DATAS"
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
  bootstrap:
    timeout: 5
    conclude_timeout: 5
  reason:
    timeout: 5
    max_intents: 1
  explore:
    timeout: 5
    conclude_timeout: 5

observability:
  enabled: false
  record: []
  record_raw_worker_stream: false
  max_event_bytes: 1024
  max_bytes_per_execution: 1024
  flush_interval_ms: 250
  flush_max_bytes: 1024
  retention_days: 1
  redaction_patterns: []

worker_runtime:
  common_env: {}
  container:
    image: "cairn/test:latest"
    network_mode: "cairn"
    completed_action: "stop"
    bind_mounts:
      - name: "ctf-attachments"
        host_path: "$HOST_DATAS/attachments"
        container_path: "/home/kali/workspace/attachments"
        read_only: true
      - name: "project-files"
        host_path: "$HOST_DATAS/project-files/{project_id}"
        container_path: "/home/kali/workspace"
        read_only: false

worker_pool:
  proxies: []
  workers:
    - name: "mock-w"
      type: "mock"
      task_types: [bootstrap, reason, explore]
      max_running: 1
      priority: 0
      env:
        MOCK_HEALTHCHECK: '{"delay":[0,1],"outcomes":{"ok":1.0,"fail":0.0}}'
        MOCK_BOOTSTRAP: '{"delay":[0,1],"outcomes":{"fact":1.0,"rejected":0.0,"invalid_json":0.0,"invalid_payload":0.0,"command_fail":0.0}}'
        MOCK_BOOTSTRAP_CONCLUDE: '{"delay":[0,1],"outcomes":{"fact":1.0,"rejected":0.0,"invalid_json":0.0,"invalid_payload":0.0,"command_fail":0.0}}'
        MOCK_REASON: '{"delay":[0,1],"outcomes":{"complete":0.0,"intent":1.0,"noop":0.0,"rejected":0.0,"invalid_json":0.0,"invalid_payload":0.0,"command_fail":0.0}}'
        MOCK_EXPLORE_EXECUTE: '{"delay":[0,1],"outcomes":{"fact":1.0,"rejected":0.0,"invalid_json":0.0,"invalid_payload":0.0,"command_fail":0.0}}'
        MOCK_EXPLORE_CONCLUDE: '{"delay":[0,1],"outcomes":{"fact":1.0,"rejected":0.0,"invalid_json":0.0,"invalid_payload":0.0,"command_fail":0.0}}'
"""


class BindMountHostPathConfigTests(unittest.TestCase):
    """End-to-end: config.yaml ``host_path`` values are used directly.

    Background: the dispatcher runs inside a container, so a relative
    path in ``host_path`` would resolve to the image's baked-in
    ``/cairn/datas/...`` and the bind mount silently degrades to an empty
    overlay. The real host path is now stored directly in config.yaml;
    ``{project_id}`` remains a runtime template for per-project isolation.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cairn-bind-mount-"))
        self.datas_dir = self.tmp / "datas"
        self.datas_dir.mkdir()
        self.config_path = self.tmp / "config.yaml"
        from helpers import split_server_dispatch_config

        combined = yaml.safe_load(_BIND_MOUNT_INTERPOLATION_YAML_TEMPLATE.replace("$HOST_DATAS", str(self.datas_dir)))
        server, dispatch = split_server_dispatch_config(combined)
        (self.tmp / "server.yaml").write_text(yaml.safe_dump(server, sort_keys=False), encoding="utf-8")
        self.config_path.write_text(yaml.safe_dump(dispatch, sort_keys=False), encoding="utf-8")
        (self.tmp / "config.resources.yaml").write_text(
            "capabilities:\n  mcp_servers: []\n  skills: []\nroles: []\n",
            encoding="utf-8",
        )
    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_host_path_uses_yaml_value(self) -> None:
        from cairn.shared.config import DispatchConfig

        cfg = DispatchConfig.load(self.config_path)
        mounts = {m.name: m for m in cfg.container.bind_mounts}
        # _resolve_bind_mount_host_path runs Path.resolve() on the host path,
        # which on macOS follows the /var/folders -> /private/var/folders
        # symlink. Compare against the resolved form to stay portable.
        expected_root = str(self.datas_dir.resolve())
        self.assertEqual(
            mounts["ctf-attachments"].host_path,
            f"{expected_root}/attachments",
        )
        self.assertEqual(
            mounts["project-files"].host_path,
            f"{expected_root}/project-files/{{project_id}}",
        )

    def test_host_path_preserves_project_id_template(self) -> None:
        """``{project_id}`` must NOT be consumed by env interpolation.

        It is expanded at container-launch time by
        ``ContainerManager._render_bind_mounts_for``. Consuming it during
        config load would break per-project isolation.
        """
        from cairn.dispatcher.runtime.containers import ContainerManager
        from cairn.shared.config import DispatchConfig

        cfg = DispatchConfig.load(self.config_path)
        host_path = next(
            m.host_path for m in cfg.container.bind_mounts if m.name == "project-files"
        )
        self.assertIn("{project_id}", host_path)
        # The runtime renderer is a pure function of (config, project_id) so
        # we can call it directly without instantiating ContainerManager
        # (and therefore without needing a docker client).
        rendered = ContainerManager._render_bind_mounts_for(cfg.container, "proj-xyz")
        rendered_paths = {m["host_path"] for m in rendered}
        expected_root = str(self.datas_dir.resolve())
        self.assertIn(f"{expected_root}/project-files/proj-xyz", rendered_paths)

    def test_deleted_dispatcher_fields_are_rejected(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        server_path = self.tmp / "server.yaml"
        data = yaml.safe_load(server_path.read_text(encoding="utf-8"))
        data["dispatcher"]["leader_ttl_seconds"] = 15
        data["worker_runtime"]["container"]["dispatcher_id"] = "old"
        server_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        with self.assertRaises(ConfigError):
            DispatchConfig.load(self.config_path)

    def test_unknown_runtime_field_is_rejected(self) -> None:
        from cairn.shared.config import ConfigError, DispatchConfig

        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        data["dispatcher"]["runtime"]["unknown_runtime_field"] = True
        self.config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        with self.assertRaises(ConfigError):
            DispatchConfig.load(self.config_path)

if __name__ == "__main__":
    unittest.main()
