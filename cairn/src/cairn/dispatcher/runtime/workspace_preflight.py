from __future__ import annotations

from typing import Any

from cairn.dispatcher.runtime.container_access import DockerAccess
from cairn.dispatcher.runtime.mounts import render_bind_mounts
from cairn.shared.config import ContainerConfig

PROJECT_FILES_MOUNT_NAME = "project-files"
PROJECT_WORKSPACE_PATH = "/home/kali/workspace"
CTF_WEB_JS_REPORT_DIR = "reports/ctf-web-js-analysis"
OUTPUT_DIRS = ("reports", "exploit", CTF_WEB_JS_REPORT_DIR)


class WorkspacePreflight:
    def __init__(
        self,
        *,
        access: DockerAccess,
        docker_exception_type: type[Exception],
    ) -> None:
        self.access = access
        self.docker_exception_type = docker_exception_type

    def run(self, container_name: str, project_id: str, config: ContainerConfig) -> None:
        mount = project_files_mount(config, project_id)
        if mount is None:
            raise RuntimeError(
                "project workspace preflight failed: missing writable project-files bind mount "
                f"at {PROJECT_WORKSPACE_PATH}"
            )
        if bool(mount["read_only"]):
            raise RuntimeError("project workspace preflight failed: project-files bind mount is read-only")

        workspace = str(mount["container_path"])
        container = self.access.require_container(container_name)
        exec_user = config.exec_user or "kali"

        setup_result = self._exec(
            container,
            _SETUP_SCRIPT,
            workspace,
            _chown_spec(exec_user),
            user="0:0",
        )
        if setup_result.exit_code != 0:
            raise RuntimeError(
                "project workspace preflight failed during root setup "
                f"code={setup_result.exit_code} output={setup_result.output.strip()}"
            )

        probe_result = self._exec(
            container,
            _WRITE_PROBE_SCRIPT,
            workspace,
            user=exec_user,
        )
        if probe_result.exit_code != 0:
            raise RuntimeError(
                "project workspace preflight failed: worker user cannot write to project-files "
                f"workspace as {exec_user} code={probe_result.exit_code} output={probe_result.output.strip()}"
            )

    def _exec(self, container: Any, script: str, *args: str, user: str | None) -> "_ExecResult":
        try:
            result = container.exec_run(
                ["/bin/sh", "-lc", script, "--", *args],
                stdout=True,
                stderr=True,
                user=user,
            )
        except self.docker_exception_type as exc:
            return _ExecResult(exit_code=1, output=str(exc))
        return _normalize_exec_result(result)


def project_files_mount(config: ContainerConfig, project_id: str) -> dict[str, object] | None:
    mounts = render_bind_mounts(config, project_id)
    by_name = [mount for mount in mounts if mount.get("name") == PROJECT_FILES_MOUNT_NAME]
    if by_name:
        return by_name[0]
    for mount in mounts:
        if mount.get("container_path") == PROJECT_WORKSPACE_PATH:
            return mount
    return None


def _chown_spec(exec_user: str) -> str:
    if ":" in exec_user:
        return exec_user
    return f"{exec_user}:{exec_user}"


class _ExecResult:
    def __init__(self, *, exit_code: int, output: str) -> None:
        self.exit_code = exit_code
        self.output = output


def _normalize_exec_result(result: Any) -> _ExecResult:
    if isinstance(result, tuple) and len(result) == 2:
        exit_code, output = result
    else:
        exit_code = getattr(result, "exit_code", 1)
        output = getattr(result, "output", "")
    if isinstance(output, bytes):
        text = output.decode("utf-8", errors="replace")
    else:
        text = str(output)
    return _ExecResult(exit_code=int(exit_code), output=text)


_SETUP_SCRIPT = r'''
workspace="$1"
owner="$2"
reports="$workspace/reports"
exploit="$workspace/exploit"
analysis="$reports/ctf-web-js-analysis"

if [ ! -d "$workspace" ]; then
  mkdir -p "$workspace" || exit 2
fi
mkdir -p "$reports" "$exploit" "$analysis" || exit 3

if chown -R "$owner" "$reports" "$exploit" 2>/tmp/cairn-workspace-chown.err; then
  exit 0
fi
if chmod -R ug+rwX "$reports" "$exploit" 2>/tmp/cairn-workspace-chmod.err; then
  exit 0
fi
chmod -R 777 "$reports" "$exploit" || exit 4
'''


_WRITE_PROBE_SCRIPT = r'''
workspace="$1"
probe="$workspace/reports/ctf-web-js-analysis/.cairn-workspace-write-test-$(date +%s)-$$"
printf ok > "$probe" || exit 5
rm -f "$probe" || exit 6
'''
