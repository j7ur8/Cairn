from __future__ import annotations

import json

from cairn.dispatcher.workers.adapters._jsonl import extract_text_parts, iter_jsonl
from cairn.dispatcher.workers.base import DriverResult, RegexSessionDriver, WorkerExecutionContext, context_workdir
from cairn.shared.config import WorkerConfig

CODEX_ENV_PREFIX = [
    "env",
    "CODEX_NON_INTERACTIVE=1",
]

CODEX_EXEC_GUARDRAILS = [
    "--ignore-user-config",
    "--skip-git-repo-check",
]
DEFAULT_CODEX_REASONING_EFFORT = "high"


class CodexDriver(RegexSessionDriver):
    type_name = "codex"

    def trace_format(self) -> str | None:
        return "codex_jsonl"

    def requires_tty(self) -> bool:
        return True

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self._build_exec(worker, "Reply with exactly pong.", ephemeral=True)

    def build_startup_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self._build_exec(worker, "Reply with exactly pong.", ephemeral=True)

    def describe_startup_healthcheck(self, worker: WorkerConfig) -> str:
        return "codex exec healthcheck via official client"

    def build_execute(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str | None,
        context: WorkerExecutionContext | None = None,
    ) -> DriverResult:
        return DriverResult(argv=self._build_exec(worker, prompt, context), workdir=context_workdir(context))

    def build_conclude(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str,
        context: WorkerExecutionContext | None = None,
    ) -> list[str]:
        env = worker.env
        return [
            *CODEX_ENV_PREFIX,
            "codex",
            "exec",
            "resume",
            *CODEX_EXEC_GUARDRAILS,
            session,
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--model",
            env["CODEX_MODEL"],
            "-c",
            'model_provider="cairn"',
            "-c",
            'model_providers.cairn.name="cairn"',
            "-c",
            'model_providers.cairn.wire_api="responses"',
            "-c",
            CodexDriver._reasoning_effort_config(env),
            "-c",
            f'model_providers.cairn.base_url="{env["CODEX_BASE_URL"]}"',
            "-c",
            'model_providers.cairn.env_key="OPENAI_API_KEY"',
            "--",
            prompt,
        ]

    @staticmethod
    def _build_exec(
        worker: WorkerConfig,
        prompt: str,
        context: WorkerExecutionContext | None = None,
        *,
        ephemeral: bool = False,
    ) -> list[str]:
        env = worker.env
        return [
            *CODEX_ENV_PREFIX,
            "codex",
            "exec",
            *(["--ephemeral"] if ephemeral else []),
            *CODEX_EXEC_GUARDRAILS,
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--model",
            env["CODEX_MODEL"],
            "-c",
            'model_provider="cairn"',
            "-c",
            'model_providers.cairn.name="cairn"',
            "-c",
            'model_providers.cairn.wire_api="responses"',
            "-c",
            CodexDriver._reasoning_effort_config(env),
            "-c",
            f'model_providers.cairn.base_url="{env["CODEX_BASE_URL"]}"',
            "-c",
            'model_providers.cairn.env_key="OPENAI_API_KEY"',
            *CodexDriver._capability_args(context),
            "--",
            prompt,
        ]

    @staticmethod
    def _capability_args(context: WorkerExecutionContext | None) -> list[str]:
        return CodexDriver._capability_args_for(context, include_skill_root=True)

    @staticmethod
    def _reasoning_effort_config(env: dict[str, str]) -> str:
        effort = (env.get("CAIRN_MODEL_REASONING_EFFORT") or DEFAULT_CODEX_REASONING_EFFORT).strip()
        return f"model_reasoning_effort={json.dumps(effort)}"

    @staticmethod
    def _capability_args_for(context: WorkerExecutionContext | None, *, include_skill_root: bool) -> list[str]:
        if context is None:
            return []
        args: list[str] = []
        if include_skill_root and context.skill_root:
            args.extend(["--add-dir", context.skill_root])
        for server in context.mcp_servers or []:
            server_id = server.get("id")
            if not isinstance(server_id, str) or not server_id:
                continue
            transport = server.get("transport", "stdio")
            prefix = f"mcp_servers.{server_id}"
            if transport == "http":
                url = server.get("url")
                if not isinstance(url, str) or not url:
                    continue
                args.extend(["-c", f"{prefix}.url={json.dumps(url)}"])
                headers = server.get("headers")
                if isinstance(headers, dict):
                    for key, value in headers.items():
                        if isinstance(key, str) and key:
                            args.extend([
                                "-c",
                                f"{prefix}.headers.{key}={json.dumps(str(value))}",
                            ])
                continue
            # stdio (default)
            command = server.get("command")
            if not isinstance(command, str) or not command:
                continue
            args.extend(["-c", f"{prefix}.command={json.dumps(command)}"])
            server_args = server.get("args")
            if isinstance(server_args, list):
                args.extend(["-c", f"{prefix}.args={json.dumps([str(item) for item in server_args])}"])
            env = server.get("env")
            if isinstance(env, dict):
                for key, value in env.items():
                    if isinstance(key, str) and key:
                        args.extend(["-c", f"{prefix}.env.{key}={json.dumps(str(value))}"])
        return args

    def extract_session(self, session: str | None, stdout: str, stderr: str) -> str | None:
        if session:
            return session
        for payload in iter_jsonl(stdout):
            if payload.get("type") == "thread.started":
                session_id = payload.get("thread_id")
                if isinstance(session_id, str) and session_id:
                    return session_id
            if payload.get("type") == "session_meta" and isinstance(payload.get("payload"), dict):
                session_id = payload["payload"].get("id")
                if isinstance(session_id, str) and session_id:
                    return session_id
        return super().extract_session(session, stdout, stderr)

    def extract_response_text(self, stdout: str, stderr: str) -> str:
        messages: list[str] = []
        for payload in iter_jsonl(stdout):
            top_type = payload.get("type")
            body = payload.get("payload")
            item = payload.get("item")
            if top_type == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
                message = item.get("text") or item.get("message")
                if isinstance(message, str) and message:
                    messages.append(message)
            if top_type == "event_msg" and isinstance(body, dict) and body.get("type") == "agent_message":
                message = body.get("message")
                if isinstance(message, str) and message:
                    messages.append(message)
            elif top_type == "response_item" and isinstance(body, dict) and body.get("type") == "message":
                text = extract_text_parts(body.get("content"))
                if text:
                    messages.append(text)
        if messages:
            return messages[-1]
        return stdout
