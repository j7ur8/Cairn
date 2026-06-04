from __future__ import annotations

import json
from typing import Any

from cairn.dispatcher.config import WorkerConfig
from cairn.dispatcher.workers.base import DriverResult, RegexSessionDriver, WorkerExecutionContext


CODEX_ENV_PREFIX = [
    "env",
    "CODEX_NON_INTERACTIVE=1",
]

CODEX_EXEC_GUARDRAILS = [
    "--ignore-user-config",
    "--ignore-rules",
    "--skip-git-repo-check",
]


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
        return DriverResult(argv=self._build_exec(worker, prompt, context))

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
            'model_reasoning_effort="high"',
            "-c",
            f'model_providers.cairn.base_url="{env["CODEX_BASE_URL"]}"',
            "-c",
            'model_providers.cairn.env_key="OPENAI_API_KEY"',
            *self._resume_capability_args(context),
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
            'model_reasoning_effort="high"',
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
    def _resume_capability_args(context: WorkerExecutionContext | None) -> list[str]:
        return CodexDriver._capability_args_for(context, include_skill_root=False)

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
                bearer_env = server.get("bearer_token_env")
                if isinstance(bearer_env, str) and bearer_env:
                    args.extend([
                        "-c",
                        f"{prefix}.bearer_token_env_var={json.dumps(bearer_env)}",
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
        for payload in _iter_jsonl(stdout):
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
        for payload in _iter_jsonl(stdout):
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
                text = _extract_text(body.get("content"))
                if text:
                    messages.append(text)
        if messages:
            return messages[-1]
        return stdout


def _iter_jsonl(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()
