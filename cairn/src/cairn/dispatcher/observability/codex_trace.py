from __future__ import annotations

from typing import Any

from cairn.dispatcher.observability.trace_base import (
    JsonLineTraceParser,
    TraceEvent,
    compact,
    extract_openai_text,
    maybe_json,
    strip_ansi,
    tool_summary,
)


class CodexTraceParser(JsonLineTraceParser):
    trace_format = "codex_jsonl"

    def _parse_non_json_line(self, line: str) -> TraceEvent | None:
        plain = strip_ansi(line).strip()
        if line == "Reading additional input from stdin...":
            return TraceEvent(
                "system_event",
                self.phase,
                "system",
                "codex cli scanned stdin for appended input",
                {"line": line, "notice_type": "stdin_scan"},
            )
        if is_codex_cli_diagnostic(plain):
            return TraceEvent(
                "error",
                self.phase,
                "error",
                plain,
                {"line": line, "notice_type": "codex_cli_diagnostic"},
            )
        return None

    def _parse_payload(self, payload: dict[str, Any]) -> list[TraceEvent]:
        top_type = payload.get("type")
        body = payload.get("payload")
        if top_type == "thread.started":
            session_id = payload.get("thread_id")
            if isinstance(session_id, str) and session_id:
                self._session_id = session_id
            return [
                TraceEvent(
                    "session_init",
                    self.phase,
                    "system",
                    "codex thread started",
                    {"session_id": session_id},
                )
            ]
        if top_type in ("turn.started", "turn.completed"):
            content = "codex turn started" if top_type == "turn.started" else "codex turn completed"
            return [TraceEvent("system_event", self.phase, "system", content, payload)]
        if top_type in ("item.started", "item.completed", "item.updated"):
            item = payload.get("item")
            if isinstance(item, dict):
                return self._parse_current_item(top_type, item)
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

    def _parse_current_item(self, event_type: str, item: dict[str, Any]) -> list[TraceEvent]:
        item_type = item.get("type")
        if item_type == "agent_message":
            text = str(item.get("text") or item.get("message") or "")
            if event_type == "item.completed" and text:
                self._final_messages.append(text)
                return [TraceEvent("agent_message", self.phase, "result", text, {"item_id": item.get("id")})]
            return []
        if item_type == "command_execution":
            command = item.get("command")
            command_text = " ".join(str(part) for part in command) if isinstance(command, list) else str(command or "")
            metadata = {
                "item_id": item.get("id"),
                "command": command,
                "exit_code": item.get("exit_code"),
                "status": item.get("status"),
                "stdout": item.get("stdout"),
                "stderr": item.get("stderr"),
                "output": item.get("aggregated_output"),
            }
            if event_type == "item.started" or item.get("status") == "in_progress":
                return [TraceEvent("command_start", self.phase, "system", command_text, metadata)]
            status = str(item.get("status") or "")
            stream = "result" if status in ("completed", "success", "") and item.get("exit_code") in (None, 0) else "error"
            return [TraceEvent("command_end", self.phase, stream, command_text or compact(str(item.get("aggregated_output") or "")), metadata)]
        if item_type == "reasoning":
            summary = item.get("summary")
            if isinstance(summary, list) and summary:
                return [TraceEvent("thinking", self.phase, "system", "\n".join(str(part) for part in summary), {"item_id": item.get("id")})]
        return []

    def _parse_response_item(self, item: dict[str, Any]) -> list[TraceEvent]:
        item_type = item.get("type")
        if item_type == "function_call":
            name = str(item.get("name") or "tool")
            arguments = maybe_json(item.get("arguments"))
            content = tool_summary(name, arguments)
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
                    compact(content),
                    {"call_id": item.get("call_id"), "output": content},
                )
            ]
        if item_type == "message":
            text = extract_openai_text(item.get("content"))
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


def is_codex_cli_diagnostic(line: str) -> bool:
    return (
        line.startswith("error:")
        or line.startswith("tip:")
        or line.startswith("Usage: codex ")
        or line.startswith("For more information, try ")
    )
