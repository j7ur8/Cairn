from __future__ import annotations

import json
import re
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
        notice = self._parse_non_json_line(line)
        if notice is not None:
            return [notice]
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

    def _parse_non_json_line(self, line: str) -> TraceEvent | None:
        return None


def maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def extract_openai_text(content: Any) -> str:
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


def tool_summary(name: str, arguments: Any) -> str:
    if isinstance(arguments, dict):
        command = arguments.get("cmd") or arguments.get("command")
        if command:
            return f"{name}: {command}"
    return name


def compact(text: str, limit: int = 1200) -> str:
    compact_text = " ".join(text.split())
    if len(compact_text) <= limit:
        return compact_text
    return compact_text[:limit] + "..."


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)
