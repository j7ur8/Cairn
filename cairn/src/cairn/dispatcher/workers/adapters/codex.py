from __future__ import annotations

import json
from typing import Any

from cairn.dispatcher.config import WorkerConfig
from cairn.dispatcher.workers.base import DriverResult, RegexSessionDriver


class CodexDriver(RegexSessionDriver):
    type_name = "codex"

    def trace_format(self) -> str | None:
        return "codex_jsonl"

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self._build_exec(worker, "Reply with exactly pong.")

    def build_startup_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self._build_exec(worker, "Reply with exactly pong.")

    def describe_startup_healthcheck(self, worker: WorkerConfig) -> str:
        return "codex exec healthcheck via official client"

    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None) -> DriverResult:
        return DriverResult(argv=self._build_exec(worker, prompt))

    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        env = worker.env
        return [
            "codex",
            "exec",
            "resume",
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
            "--",
            prompt,
        ]

    @staticmethod
    def _build_exec(worker: WorkerConfig, prompt: str) -> list[str]:
        env = worker.env
        return [
            "codex",
            "exec",
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
            "--",
            prompt,
        ]

    def extract_session(self, session: str | None, stdout: str, stderr: str) -> str | None:
        if session:
            return session
        for payload in _iter_jsonl(stdout):
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
