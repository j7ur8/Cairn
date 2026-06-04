"""Tests for the ``container.user`` field and the EPERM-safe bind-mount chmod.

Background: on macOS Docker Desktop, the worker container (running as
``kali`` = UID 1000) cannot write to a host bind mount that is owned by a
different UID. The fix is to let the operator configure ``container.user``
to match the host user's ``uid:gid`` and pass it through to
``docker.containers.run``. The chmod helper also needs to be EPERM-safe
because the dispatcher itself runs as non-root inside its own container.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Schema: ContainerConfig.user
# ---------------------------------------------------------------------------


class _ContainerConfigHarness:
    """Build a ContainerConfig with a minimal but valid bind_mounts list."""

    @staticmethod
    def _build(user=None):
        from cairn.dispatcher.config import BindMountConfig, ContainerConfig

        return ContainerConfig(
            image="cairn/test:latest",
            user=user,
            network_mode="cairn",
            completed_action="stop",
            bind_mounts=[
                BindMountConfig(
                    name="project-files",
                    host_path="./datas/project-files/{project_id}",
                    container_path="/mnt/project",
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
        from cairn.dispatcher.config import ContainerConfig, BindMountConfig

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
        self.containers.get.side_effect = NotFound("not found")
        self.containers.run.return_value = MagicMock()

    def install(self):
        return patch("docker.from_env", return_value=self.client)


class ContainerUserRuntimeTests(unittest.TestCase):
    def _make_manager(self, user, exec_user=None, dispatcher_id="default"):
        from cairn.dispatcher.config import BindMountConfig, ContainerConfig
        from cairn.dispatcher.runtime.containers import ContainerManager

        cfg = ContainerConfig(
            image="cairn/test:latest",
            dispatcher_id=dispatcher_id,
            user=user,
            exec_user=exec_user,
            network_mode="cairn",
            completed_action="stop",
            bind_mounts=[
                BindMountConfig(
                    name="project-files",
                    host_path="./datas/project-files/{project_id}",
                    container_path="/mnt/project",
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

    def test_container_name_includes_dispatcher_id(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="0:0", dispatcher_id="d1")

        self.assertEqual(mgr.container_name("proj-1"), "cairn-dispatch-d1-proj-1")

    def test_created_container_receives_owner_labels(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="0:0", dispatcher_id="d1")
            mgr.ensure_running("proj-1")

        kwargs = dm.containers.run.call_args.kwargs
        self.assertEqual(kwargs["labels"]["cairn.managed"], "true")
        self.assertEqual(kwargs["labels"]["cairn.dispatcher_id"], "d1")
        self.assertEqual(kwargs["labels"]["cairn.project_id"], "proj-1")
        self.assertEqual(kwargs["labels"]["cairn.startup_healthcheck"], "false")

    def test_startup_container_also_receives_user(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="501:20")
            mgr.create_startup_container()

        self.assertEqual(dm.containers.run.call_count, 1)
        kwargs = dm.containers.run.call_args.kwargs
        self.assertEqual(kwargs.get("user"), "501:20")

    def test_startup_container_receives_owner_labels(self):
        dm = _DockerMock()
        with dm.install():
            mgr = self._make_manager(user="0:0", dispatcher_id="d1")
            mgr.create_startup_container()

        kwargs = dm.containers.run.call_args.kwargs
        self.assertEqual(kwargs["labels"]["cairn.dispatcher_id"], "d1")
        self.assertEqual(kwargs["labels"]["cairn.project_id"], "startup-healthcheck")
        self.assertEqual(kwargs["labels"]["cairn.startup_healthcheck"], "true")

    def test_managed_container_names_filters_by_dispatcher_label(self):
        dm = _DockerMock()
        dm.containers.list.return_value = [
            type("C", (), {"name": "cairn-dispatch-d1-proj-1"})(),
        ]
        with dm.install():
            mgr = self._make_manager(user="0:0", dispatcher_id="d1")
            names = mgr.managed_container_names()

        self.assertEqual(names, ["cairn-dispatch-d1-proj-1"])
        dm.containers.list.assert_called_once_with(
            all=True,
            filters={
                "label": [
                    "cairn.managed=true",
                    "cairn.dispatcher_id=d1",
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


# ---------------------------------------------------------------------------
# _ensure_world_writable_dir: EPERM must not raise
# ---------------------------------------------------------------------------


class EnsureWorldWritableDirEpermTests(unittest.TestCase):
    def test_permission_error_does_not_raise(self):
        from cairn.dispatcher.runtime.containers import _ensure_world_writable_dir

        fake_path = Path("/fake/host/bind/mount")
        with patch.object(Path, "stat", return_value=type("S", (), {"st_mode": 0o755})()):
            with patch.object(
                os,
                "chmod",
                side_effect=PermissionError(1, "operation not permitted"),
            ):
                # Must not raise. A warning is logged.
                _ensure_world_writable_dir(fake_path)

    def test_already_world_writable_skips_chmod(self):
        from cairn.dispatcher.runtime.containers import _ensure_world_writable_dir

        fake_path = Path("/fake/host/bind/mount")
        # 0o002 = world-writable bit already set -> early return, no chmod call.
        with patch.object(Path, "stat", return_value=type("S", (), {"st_mode": 0o777})()):
            with patch.object(os, "chmod") as chmod:
                _ensure_world_writable_dir(fake_path)
                chmod.assert_not_called()


if __name__ == "__main__":
    unittest.main()
