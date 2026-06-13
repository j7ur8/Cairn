from __future__ import annotations

import json
from typing import Any

from cairn.dispatcher.observability.trace_base import JsonLineTraceParser, TraceEvent, compact, tool_summary


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
        elif subtype_text == "thinking_tokens":
            return TraceEvent("usage", self.phase, "system", "token usage", payload)
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
                    events.append(TraceEvent("tool_call", self.phase, "system", tool_summary(name, arguments), metadata))
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
                        compact(text),
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
                    str(command or compact(stdout_text or stderr_text)),
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
