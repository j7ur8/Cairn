from __future__ import annotations

import abc
import re
import shlex
import uuid
from dataclasses import dataclass
from typing import Any

from cairn.shared.config import WorkerConfig


@dataclass(slots=True)
class DriverResult:
    argv: list[str]
    session: str | None = None
    workdir: str | None = None


@dataclass(slots=True)
class WorkerExecutionContext:
    capability_root: str = ""
    mcp_config_path: str = ""
    skill_root: str = ""
    claude_plugin_dir: str = ""
    task_workspace: str = ""
    instruction_root: str = ""
    claude_md_path: str = ""
    agents_md_path: str = ""
    policy_path: str = ""
    mcp_servers: list[dict[str, Any]] | None = None
    skills: list[str] | None = None


class WorkerDriver(abc.ABC):
    type_name: str

    def supports_conclude(self) -> bool:
        return True

    def prepare_session(self) -> str | None:
        return None

    def trace_format(self) -> str | None:
        return None

    def requires_tty(self) -> bool:
        return False

    def build_startup_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self.build_healthcheck(worker)

    def describe_startup_healthcheck(self, worker: WorkerConfig) -> str:
        return shlex.join(self.build_startup_healthcheck(worker))

    @abc.abstractmethod
    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def build_execute(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str | None,
        context: WorkerExecutionContext | None = None,
    ) -> DriverResult:
        raise NotImplementedError

    @abc.abstractmethod
    def build_conclude(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str,
        context: WorkerExecutionContext | None = None,
    ) -> list[str]:
        raise NotImplementedError

    def extract_session(self, session: str | None, stdout: str, stderr: str) -> str | None:
        return session

    def extract_response_text(self, stdout: str, stderr: str) -> str:
        return stdout


def context_workdir(context: WorkerExecutionContext | None) -> str | None:
    if context is None:
        return None
    return context.instruction_root or context.task_workspace or None


class SeedSessionDriver(WorkerDriver):
    def prepare_session(self) -> str | None:
        return str(uuid.uuid4())


class RegexSessionDriver(WorkerDriver):
    session_pattern = re.compile(r"session id:\s*([0-9a-fA-F-]+)")

    def extract_session(self, session: str | None, stdout: str, stderr: str) -> str | None:
        if session:
            return session
        match = self.session_pattern.search(stderr)
        if match:
            return match.group(1)
        return None
