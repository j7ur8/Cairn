from __future__ import annotations

import json

LLM_EVENT_KIND_OPTIONS: tuple[str, ...] = (
    "prompt",
    "stdout",
    "stderr",
    "model_response",
    "parse_error",
    "timeout",
    "cancelled",
    "process_end",
    "result",
    "error",
    "agent_message",
    "thinking",
    "tool_call",
    "tool_result",
    "command_start",
    "command_end",
    "usage",
    "session_init",
    "api_retry",
    "system_event",
    "capability_manifest",
    "trace_parse_error",
)
DEFAULT_LLM_HIDDEN_EVENT_KINDS: tuple[str, ...] = ("usage",)


def normalize_llm_event_kinds(value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return list(LLM_EVENT_KIND_OPTIONS)
    allowed = set(LLM_EVENT_KIND_OPTIONS)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            raise ValueError("event kind must not be empty")
        if text not in allowed:
            raise ValueError(f"unknown event kind: {text}")
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def hidden_kinds_from_visible(value: list[str] | tuple[str, ...] | None) -> list[str]:
    visible = set(normalize_llm_event_kinds(value))
    return [kind for kind in LLM_EVENT_KIND_OPTIONS if kind not in visible]


def visible_kinds_from_hidden(value: list[str] | tuple[str, ...] | None) -> list[str]:
    hidden = set(normalize_llm_event_kinds(value))
    return [kind for kind in LLM_EVENT_KIND_OPTIONS if kind not in hidden]


def parse_llm_hidden_event_kinds(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    if not isinstance(raw, list):
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    try:
        return normalize_llm_event_kinds(raw)
    except ValueError:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
