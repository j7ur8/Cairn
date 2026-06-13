from __future__ import annotations

from collections.abc import Callable

from cairn.dispatcher.runtime.container_access import DockerAccess
from cairn.dispatcher.runtime.process import ManagedProcess
from cairn.shared.config import ContainerConfig


class ContainerExec:
    def __init__(
        self,
        *,
        config: ContainerConfig,
        access: DockerAccess,
        require_container: Callable[[str], object] | None = None,
    ) -> None:
        self.config = config
        self.access = access
        self.require_container = require_container or access.require_container

    def build_exec_process(
        self,
        container_name: str,
        env: dict[str, str],
        command: list[str],
        timeout_seconds: int | None = None,
        kill_after_seconds: int = 5,
        tty: bool = False,
        on_output: Callable[[str, str], None] | None = None,
    ) -> ManagedProcess:
        container = self.require_container(container_name)
        argv: list[str] = []
        if timeout_seconds is not None:
            argv.extend(["timeout", "-k", f"{kill_after_seconds}s", f"{timeout_seconds}s"])
        argv.extend(command)
        return ManagedProcess(container, argv, env, user=self.config.exec_user, tty=tty, on_output=on_output)
