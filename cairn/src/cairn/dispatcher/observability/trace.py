from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TraceEvent:
    kind: str
    phase: str
    stream: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def formatted_content(self) -> str:
        if not self.metadata:
            return self.content
        payload = {
            "summary": self.content,
            **self.metadata,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


class JsonLineTraceParser:
    trace_format = "plain"

    def __init__(self, phase: str):
        self.phase = phase
        self._buffer = ""
        self._final_messages: list[str] = []
        self._session_id: str | None = None

    @property
    def final_text(self) -> str:
        return "\n".join(item for item in self._final_messages if item).strip()

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def feed(self, chunk: str) -> list[TraceEvent]:
        if not chunk:
            return []
        self._buffer += chunk
        events: list[TraceEvent] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                events.extend(self._parse_line(line))
        return events

    def finish(self) -> list[TraceEvent]:
        line = self._buffer.strip()
        self._buffer = ""
        if not line:
            return []
        return self._parse_line(line)

    def _parse_line(self, line: str) -> list[TraceEvent]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            return [
                TraceEvent(
                    "trace_parse_error",
                    self.phase,
                    "error",
                    f"failed to parse {self.trace_format} line: {exc}",
                    {"line_preview": line[:500]},
                )
            ]
        if not isinstance(payload, dict):
            return []
        return self._parse_payload(payload)

    def _parse_payload(self, payload: dict[str, Any]) -> list[TraceEvent]:
        return []


class CodexTraceParser(JsonLineTraceParser):
    trace_format = "codex_jsonl"

    def _parse_payload(self, payload: dict[str, Any]) -> list[TraceEvent]:
        top_type = payload.get("type")
        body = payload.get("payload")
        if top_type == "session_meta" and isinstance(body, dict):
            session_id = body.get("id")
            if isinstance(session_id, str) and session_id:
                self._session_id = session_id
            return []
        if top_type == "response_item" and isinstance(body, dict):
            return self._parse_response_item(body)
        if top_type == "event_msg" and isinstance(body, dict):
            return self._parse_event_msg(body)
        return []

    def _parse_response_item(self, item: dict[str, Any]) -> list[TraceEvent]:
        item_type = item.get("type")
        if item_type == "function_call":
            name = str(item.get("name") or "tool")
            arguments = _maybe_json(item.get("arguments"))
            content = _tool_summary(name, arguments)
            metadata = {"tool": name, "call_id": item.get("call_id"), "arguments": arguments}
            if name == "exec_command" and isinstance(arguments, dict):
                metadata["command"] = arguments.get("cmd")
                metadata["workdir"] = arguments.get("workdir")
                return [
                    TraceEvent("tool_call", self.phase, "system", content, metadata),
                    TraceEvent(
                        "command_start",
                        self.phase,
                        "system",
                        str(arguments.get("cmd") or content),
                        {"call_id": item.get("call_id"), "workdir": arguments.get("workdir")},
                    ),
                ]
            return [TraceEvent("tool_call", self.phase, "system", content, metadata)]
        if item_type == "function_call_output":
            content = str(item.get("output") or "")
            return [
                TraceEvent(
                    "tool_result",
                    self.phase,
                    "result",
                    _compact(content),
                    {"call_id": item.get("call_id"), "output": content},
                )
            ]
        if item_type == "message":
            text = _extract_openai_text(item.get("content"))
            if text:
                self._final_messages.append(text)
                return [TraceEvent("agent_message", self.phase, "result", text)]
        if item_type == "reasoning":
            summary = item.get("summary")
            if isinstance(summary, list) and summary:
                text = "\n".join(str(part) for part in summary)
                return [TraceEvent("thinking", self.phase, "system", text)]
        return []

    def _parse_event_msg(self, msg: dict[str, Any]) -> list[TraceEvent]:
        msg_type = msg.get("type")
        if msg_type == "agent_message":
            message = str(msg.get("message") or "")
            phase = str(msg.get("phase") or self.phase)
            return [TraceEvent("agent_message", phase, "result", message)]
        if msg_type == "exec_command_end":
            command = msg.get("command")
            command_text = " ".join(str(part) for part in command) if isinstance(command, list) else str(command or "")
            content = command_text or str(msg.get("aggregated_output") or "")
            return [
                TraceEvent(
                    "command_end",
                    self.phase,
                    "result" if msg.get("status") == "completed" else "error",
                    content,
                    {
                        "call_id": msg.get("call_id"),
                        "command": command,
                        "cwd": msg.get("cwd"),
                        "exit_code": msg.get("exit_code"),
                        "duration": msg.get("duration"),
                        "status": msg.get("status"),
                        "stdout": msg.get("stdout"),
                        "stderr": msg.get("stderr"),
                        "output": msg.get("aggregated_output"),
                    },
                )
            ]
        if msg_type == "token_count":
            return [TraceEvent("usage", self.phase, "system", "token usage", msg)]
        return []


class ClaudeTraceParser(JsonLineTraceParser):
    trace_format = "claude_stream_json"

    def _parse_payload(self, payload: dict[str, Any]) -> list[TraceEvent]:
        session_id = payload.get("session_id") or payload.get("sessionId")
        if isinstance(session_id, str) and session_id:
            self._session_id = session_id

        events: list[TraceEvent] = []
        msg_type = payload.get("type")
        if msg_type == "assistant" and isinstance(payload.get("message"), dict):
            events.extend(self._parse_assistant_message(payload["message"]))
        elif msg_type == "user" and isinstance(payload.get("message"), dict):
            events.extend(self._parse_user_message(payload))
        elif msg_type == "result":
            result = payload.get("result")
            if isinstance(result, str) and result:
                self._final_messages.append(result)
                events.append(TraceEvent("agent_message", self.phase, "result", result))
            usage = payload.get("usage")
            if isinstance(usage, dict):
                events.append(TraceEvent("usage", self.phase, "system", "token usage", usage))
        elif msg_type == "system":
            event = self._parse_system_event(payload)
            if event is not None:
                events.append(event)
        return events

    def _parse_system_event(self, payload: dict[str, Any]) -> TraceEvent | None:
        subtype = payload.get("subtype")
        if not subtype:
            return None
        subtype_text = str(subtype)
        if subtype_text == "init":
            kind = "session_init"
            content = "session init"
        elif subtype_text == "api_retry":
            kind = "api_retry"
            attempt = payload.get("attempt")
            max_retries = payload.get("max_retries")
            if attempt is not None and max_retries is not None:
                content = f"api retry {attempt}/{max_retries}"
            else:
                content = "api retry"
        else:
            kind = "system_event"
            content = f"system: {subtype_text}"
        return TraceEvent(kind, self.phase, "system", content, payload)

    def _parse_assistant_message(self, message: dict[str, Any]) -> list[TraceEvent]:
        events: list[TraceEvent] = []
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type == "text":
                    text = str(item.get("text") or "")
                    if text:
                        self._final_messages.append(text)
                        events.append(TraceEvent("agent_message", self.phase, "result", text))
                elif item_type == "thinking":
                    thinking = str(item.get("thinking") or "")
                    if thinking:
                        events.append(TraceEvent("thinking", self.phase, "system", thinking))
                elif item_type == "tool_use":
                    name = str(item.get("name") or "tool")
                    arguments = item.get("input") if isinstance(item.get("input"), dict) else {}
                    metadata = {"tool": name, "call_id": item.get("id"), "arguments": arguments}
                    events.append(TraceEvent("tool_call", self.phase, "system", _tool_summary(name, arguments), metadata))
                    if name == "Bash" and isinstance(arguments, dict):
                        events.append(
                            TraceEvent(
                                "command_start",
                                self.phase,
                                "system",
                                str(arguments.get("command") or ""),
                                {"call_id": item.get("id"), "description": arguments.get("description")},
                            )
                        )
        usage = message.get("usage")
        if isinstance(usage, dict):
            events.append(TraceEvent("usage", self.phase, "system", "token usage", usage))
        return events

    def _parse_user_message(self, payload: dict[str, Any]) -> list[TraceEvent]:
        message = payload["message"]
        events: list[TraceEvent] = []
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                tool_use_id = item.get("tool_use_id")
                result_content = item.get("content")
                text = result_content if isinstance(result_content, str) else json.dumps(result_content, ensure_ascii=False, default=str)
                events.append(
                    TraceEvent(
                        "tool_result",
                        self.phase,
                        "error" if item.get("is_error") else "result",
                        _compact(text),
                        {"call_id": tool_use_id, "is_error": item.get("is_error"), "output": text},
                    )
                )

        tool_result = payload.get("toolUseResult")
        if isinstance(tool_result, dict):
            stdout = tool_result.get("stdout")
            stderr = tool_result.get("stderr")
            stdout_text = stdout if isinstance(stdout, str) else ""
            stderr_text = stderr if isinstance(stderr, str) else ""
            interrupted = bool(tool_result.get("interrupted"))
            is_error = bool(tool_result.get("is_error") or tool_result.get("isError") or interrupted or stderr_text)
            command = tool_result.get("command")
            events.append(
                TraceEvent(
                    "command_end",
                    self.phase,
                    "error" if is_error else "result",
                    str(command or _compact(stdout_text or stderr_text)),
                    {
                        "command": command,
                        "stdout": stdout_text,
                        "stderr": stderr_text,
                        "interrupted": interrupted,
                        "exit_code": tool_result.get("exitCode") or tool_result.get("exit_code"),
                    },
                )
            )
        return events


def make_trace_parser(trace_format: str | None, phase: str) -> JsonLineTraceParser | None:
    if trace_format == "codex_jsonl":
        return CodexTraceParser(phase)
    if trace_format == "claude_stream_json":
        return ClaudeTraceParser(phase)
    return None


def _maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _extract_openai_text(content: Any) -> str:
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
            continue
        if item.get("type") in ("output_text", "input_text") and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts).strip()


def _tool_summary(name: str, arguments: Any) -> str:
    if isinstance(arguments, dict):
        command = arguments.get("cmd") or arguments.get("command")
        if command:
            return f"{name}: {command}"
    return name


def _compact(text: str, limit: int = 1200) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
