from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class WorkspacePreflightTests(unittest.TestCase):
    def _config(self, *, exec_user: str = "kali", read_only: bool = False):
        from cairn.shared.config import BindMountConfig, ContainerConfig

        return ContainerConfig(
            image="cairn/test:latest",
            user="0:0",
            exec_user=exec_user,
            network_mode="cairn",
            completed_action="stop",
            bind_mounts=[
                BindMountConfig(
                    name="project-files",
                    host_path="./datas/project-files/{project_id}",
                    container_path="/home/kali/workspace",
                    read_only=read_only,
                ),
            ],
        )

    def _preflight(self, container):
        from cairn.dispatcher.runtime.container_access import DockerAccess
        from cairn.dispatcher.runtime.workspace_preflight import WorkspacePreflight

        client = MagicMock()
        client.containers.get.return_value = container
        access = DockerAccess(client, docker_exception_type=Exception, not_found_type=KeyError)
        return WorkspacePreflight(access=access, docker_exception_type=Exception)

    def test_creates_output_dirs_as_root_and_probes_ctf_report_dir_as_kali(self) -> None:
        container = MagicMock()
        container.exec_run.return_value = type("R", (), {"exit_code": 0, "output": b""})()

        self._preflight(container).run("cairn-worker-proj-1", "proj-1", self._config())

        calls = container.exec_run.call_args_list
        self.assertEqual(calls[0].kwargs["user"], "0:0")
        self.assertEqual(calls[1].kwargs["user"], "kali")
        self.assertIn("mkdir -p", calls[0].args[0][2])
        self.assertIn("reports/ctf-web-js-analysis", calls[0].args[0][2])
        self.assertIn("reports/ctf-web-js-analysis/.cairn-workspace-write-test", calls[1].args[0][2])

    def test_chown_spec_accepts_numeric_exec_user(self) -> None:
        container = MagicMock()
        container.exec_run.return_value = type("R", (), {"exit_code": 0, "output": b""})()

        self._preflight(container).run("cairn-worker-proj-1", "proj-1", self._config(exec_user="1000:1000"))

        setup_argv = container.exec_run.call_args_list[0].args[0]
        self.assertEqual(setup_argv[-1], "1000:1000")

    def test_read_only_project_files_mount_fails(self) -> None:
        container = MagicMock()

        with self.assertRaises(RuntimeError) as ctx:
            self._preflight(container).run("cairn-worker-proj-1", "proj-1", self._config(read_only=True))

        self.assertIn("read-only", str(ctx.exception))
        container.exec_run.assert_not_called()

    def test_worker_write_probe_failure_blocks_task_start(self) -> None:
        container = MagicMock()
        container.exec_run.side_effect = [
            type("R", (), {"exit_code": 0, "output": b""})(),
            type("R", (), {"exit_code": 5, "output": b"permission denied"})(),
        ]

        with self.assertRaises(RuntimeError) as ctx:
            self._preflight(container).run("cairn-worker-proj-1", "proj-1", self._config())

        self.assertIn("worker user cannot write", str(ctx.exception))
        self.assertIn("permission denied", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
