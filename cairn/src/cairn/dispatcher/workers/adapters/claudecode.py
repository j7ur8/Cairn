from __future__ import annotations

import json
from typing import Any

from cairn.dispatcher.config import WorkerConfig
from cairn.dispatcher.workers.adapters._curl import build_verbose_curl_healthcheck, expand_env, render_curl_command
from cairn.dispatcher.workers.base import DriverResult, SeedSessionDriver, WorkerExecutionContext


ANTHROPIC_VERSION = "2023-06-01"


class ClaudeCodeDriver(SeedSessionDriver):
    type_name = "claudecode"

    def trace_format(self) -> str | None:
        return "claude_stream_json"

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        env = worker.env
        return [
            "curl",
            "-sS",
            "--fail",
            "-o",
            "/dev/null",
            f"{env['ANTHROPIC_BASE_URL']}/v1/messages",
            "-H",
            f"Authorization: Bearer {env['ANTHROPIC_AUTH_TOKEN']}",
            "-H",
            f"anthropic-version: {ANTHROPIC_VERSION}",
            "-H",
            "content-type: application/json",
            "-d",
            (
                '{"model":"'
                + env["ANTHROPIC_MODEL"]
                + '","max_tokens":10,"messages":[{"role":"user","content":"ping"}]}'
            ),
        ]

    def build_startup_healthcheck(self, worker: WorkerConfig) -> list[str]:
        env = worker.env
        return build_verbose_curl_healthcheck(
            f"{env['ANTHROPIC_BASE_URL']}/v1/messages",
            headers=[
                "-H",
                f"Authorization: Bearer {env['ANTHROPIC_AUTH_TOKEN']}",
                "-H",
                f"anthropic-version: {ANTHROPIC_VERSION}",
                "-H",
                "content-type: application/json",
            ],
            payload=(
                '{"model":"'
                + env["ANTHROPIC_MODEL"]
                + '","max_tokens":10,"messages":[{"role":"user","content":"ping"}]}'
            ),
        )

    def describe_startup_healthcheck(self, worker: WorkerConfig) -> str:
        env = worker.env
        return render_curl_command(
            f"{env['ANTHROPIC_BASE_URL']}/v1/messages",
            headers=[
                "-H",
                expand_env("Authorization: Bearer $ANTHROPIC_AUTH_TOKEN"),
                "-H",
                f"anthropic-version: {ANTHROPIC_VERSION}",
                "-H",
                "content-type: application/json",
            ],
            payload=(
                '{"model":"'
                + env["ANTHROPIC_MODEL"]
                + '","max_tokens":10,"messages":[{"role":"user","content":"ping"}]}'
            ),
        )

    def build_execute(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str | None,
        context: WorkerExecutionContext | None = None,
    ) -> DriverResult:
        assert session is not None
        capability_args = self._capability_args(context)
        return DriverResult(
            argv=[
                "claude",
                "--session-id",
                session,
                "--dangerously-skip-permissions",
                "--print",
                "--output-format",
                "stream-json",
                "--verbose",
                *capability_args,
                "--",
                prompt,
            ],
            session=session,
        )

    def build_conclude(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str,
        context: WorkerExecutionContext | None = None,
    ) -> list[str]:
        capability_args = self._capability_args(context)
        return [
            "claude",
            "-r",
            session,
            "--dangerously-skip-permissions",
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            *capability_args,
            "--",
            prompt,
        ]

    @staticmethod
    def _capability_args(context: WorkerExecutionContext | None) -> list[str]:
        if context is None:
            return []
        args: list[str] = []
        if context.mcp_config_path:
            args.extend(["--mcp-config", context.mcp_config_path])
        if context.skill_root:
            args.extend(["--add-dir", context.skill_root])
        return args

    def extract_response_text(self, stdout: str, stderr: str) -> str:
        messages: list[str] = []
        for payload in _iter_jsonl(stdout):
            payload_type = payload.get("type")
            if payload_type == "assistant" and isinstance(payload.get("message"), dict):
                text = _extract_assistant_text(payload["message"].get("content"))
                if text:
                    messages.append(text)
            elif payload_type == "result":
                result = payload.get("result")
                if isinstance(result, str) and result:
                    messages.append(result)
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


def _extract_assistant_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts).strip()
