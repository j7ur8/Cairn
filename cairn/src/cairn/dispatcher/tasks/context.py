from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.process import ManagedProcess
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail


class ContainerRuntime(Protocol):
    def ensure_running(self, project_id: str) -> str: ...

    def build_exec_process(
        self,
        container_name: str,
        env: dict[str, str],
        command: list[str],
        timeout_seconds: int | None = None,
        kill_after_seconds: int = 5,
        tty: bool = False,
        on_output: object | None = None,
    ) -> ManagedProcess: ...

    def write_text_file(self, container_name: str, path: str, content: str) -> None: ...


@dataclass(slots=True)
class TaskServices:
    config: DispatchConfig
    client: CairnClient
    container_runtime: ContainerRuntime


@dataclass(slots=True)
class TaskInvocation:
    project: ProjectDetail
    worker: WorkerConfig
    execution_config: dict
    cancellation: TaskCancellation
    intent: Intent | None = None
    export_yaml: str | None = None
    reason_run_id: str | None = None
    reason_trigger: str | None = None
    reason_trigger_hash: str | None = None
    fact_count: int = 0
    hint_count: int = 0
    open_intent_count: int = 0
