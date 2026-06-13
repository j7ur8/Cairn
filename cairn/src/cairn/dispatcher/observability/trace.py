from __future__ import annotations

from typing import Any

from cairn.dispatcher.observability.claude_trace import ClaudeTraceParser
from cairn.dispatcher.observability.codex_trace import CodexTraceParser, is_codex_cli_diagnostic
from cairn.dispatcher.observability.trace_base import (
    JsonLineTraceParser,
    TraceEvent,
    compact,
    extract_openai_text,
    maybe_json,
    strip_ansi,
    tool_summary,
)


def make_trace_parser(trace_format: str | None, phase: str) -> JsonLineTraceParser | None:
    if trace_format == "codex_jsonl":
        return CodexTraceParser(phase)
    if trace_format == "claude_stream_json":
        return ClaudeTraceParser(phase)
    return None


def _maybe_json(value: Any) -> Any:
    return maybe_json(value)


def _extract_openai_text(content: Any) -> str:
    return extract_openai_text(content)


def _tool_summary(name: str, arguments: Any) -> str:
    return tool_summary(name, arguments)


def _compact(text: str, limit: int = 1200) -> str:
    return compact(text, limit)


def _strip_ansi(text: str) -> str:
    return strip_ansi(text)


def _is_codex_cli_diagnostic(line: str) -> bool:
    return is_codex_cli_diagnostic(line)


__all__ = [
    "ClaudeTraceParser",
    "CodexTraceParser",
    "JsonLineTraceParser",
    "TraceEvent",
    "make_trace_parser",
]
