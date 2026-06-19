from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from cairn.server.observability._shared import normalize_event_kind_filter, row_to_event
from cairn.server.observability.event_repository import LlmEventRepository
from cairn.server.observability.models import EventCardPageResponse, LlmEventCard

_MERGEABLE_KINDS = {"tool_call", "tool_result", "command_start", "command_end"}


@dataclass(frozen=True)
class _CardPageState:
    project_id: str
    execution_id: str
    event_kinds_mode: str
    event_kinds: tuple[str, ...]
    offset: int


@dataclass(frozen=True)
class _MergedGroup:
    tool_call: Any | None = None
    tool_result: Any | None = None
    command_start: Any | None = None
    command_end: Any | None = None
    tool_call_payload: dict[str, Any] | None = None
    tool_result_payload: dict[str, Any] | None = None
    command_start_payload: dict[str, Any] | None = None
    command_end_payload: dict[str, Any] | None = None
    first_index: int = 0


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text.startswith("{") or not text.endswith("}"):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _field_text(key: str, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        if key == "command" and all(isinstance(item, (str, int, float)) for item in value):
            return " ".join(str(item) for item in value)
        return json.dumps(value, indent=2)
    if isinstance(value, dict):
        return json.dumps(value, indent=2)
    return str(value)


def _command_event_key(event: Any, payload: dict[str, Any]) -> str:
    scope = f"{event.execution_id or ''}:{event.phase or ''}"
    item_id = payload.get("item_id")
    if item_id:
        return f"{scope}:item:{item_id}"
    call_id = payload.get("call_id")
    if call_id:
        return f"{scope}:call:{call_id}"
    command = _field_text("command", payload.get("command") or payload.get("summary") or event.content or "").strip()
    return f"{scope}:command:{command}" if command else ""


def _build_merged_call_event(group: _MergedGroup) -> LlmEventCard:
    tool_call = group.tool_call
    tool_result = group.tool_result
    command_start = group.command_start
    command_end = group.command_end
    tool_call_payload = group.tool_call_payload or {}
    tool_result_payload = group.tool_result_payload or {}
    command_start_payload = group.command_start_payload or {}
    command_end_payload = group.command_end_payload or {}
    source = command_end or tool_result or command_start or tool_call
    assert source is not None

    payload: dict[str, Any] = {
        **tool_call_payload,
        **command_start_payload,
        **command_end_payload,
        **tool_result_payload,
    }

    if tool_call_payload.get("tool"):
        payload["tool"] = tool_call_payload["tool"]

    if not payload.get("command"):
        if command_start_payload.get("command"):
            payload["command"] = command_start_payload["command"]
        elif command_end_payload.get("command"):
            payload["command"] = command_end_payload["command"]
        else:
            arguments = tool_call_payload.get("arguments")
            if isinstance(arguments, dict) and arguments.get("cmd"):
                payload["command"] = arguments["cmd"]

    if not payload.get("workdir"):
        arguments = tool_call_payload.get("arguments")
        payload["workdir"] = (
            command_start_payload.get("workdir")
            or command_end_payload.get("cwd")
            or (arguments.get("workdir") if isinstance(arguments, dict) else None)
            or payload.get("workdir")
        )
    if not payload.get("cwd"):
        payload["cwd"] = command_end_payload.get("cwd") or command_start_payload.get("workdir") or payload.get("workdir")

    if command_end_payload.get("output") is not None:
        payload["output"] = command_end_payload["output"]
    elif tool_result_payload.get("output") is not None and payload.get("output") is None:
        payload["output"] = tool_result_payload["output"]
    if command_end_payload.get("stdout") is not None:
        payload["stdout"] = command_end_payload["stdout"]
    if command_end_payload.get("stderr") is not None:
        payload["stderr"] = command_end_payload["stderr"]
    if command_end_payload.get("exit_code") is not None:
        payload["exit_code"] = command_end_payload["exit_code"]
    if command_end_payload.get("duration") is not None:
        payload["duration"] = command_end_payload["duration"]
    if tool_result_payload.get("is_error") is not None and payload.get("is_error") is None:
        payload["is_error"] = tool_result_payload["is_error"]

    if command_end_payload.get("status"):
        payload["status"] = command_end_payload["status"]
    elif command_end:
        payload["status"] = "completed"
    elif command_start:
        payload["status"] = "in_progress"
    elif tool_result:
        payload["status"] = "completed"
    else:
        payload["status"] = "pending"

    payload["started_sequence"] = command_start.sequence if command_start else (tool_call.sequence if tool_call else None)
    payload["ended_sequence"] = command_end.sequence if command_end else (tool_result.sequence if tool_result else None)

    tool_name = str(tool_call_payload.get("tool") or "")
    command_text = _field_text("command", payload.get("command") or payload.get("summary") or "").strip()
    if tool_name and command_text:
        payload["summary"] = f"{tool_name} · {command_text}"
    elif tool_name:
        payload["summary"] = tool_name
    elif command_text:
        payload["summary"] = command_text
    elif not payload.get("summary"):
        payload["summary"] = "call"

    content_string = json.dumps(payload, indent=2)
    merged = {
        **source.model_dump(),
        "event_kind": "command_end",
        "stream": source.stream or ("system" if command_end else "result"),
        "content": content_string,
        "_merged_call": True,
        "_parsedPayload": payload,
    }
    return LlmEventCard.model_validate(merged)


def merge_event_cards(events: list[Any]) -> list[LlmEventCard]:
    merged: list[LlmEventCard | None] = []
    groups: dict[str, _MergedGroup] = {}

    for event in events:
        if event.event_kind not in _MERGEABLE_KINDS:
            merged.append(LlmEventCard.model_validate(event.model_dump()))
            continue
        payload = _parse_json_object(event.content) or {}
        key = _command_event_key(event, payload)
        if not key:
            merged.append(LlmEventCard.model_validate(event.model_dump()))
            continue

        group = groups.get(key)
        if group is None:
            group = _MergedGroup(first_index=len(merged))
            groups[key] = group
            merged.append(None)

        if event.event_kind == "tool_call":
            group = _MergedGroup(
                tool_call=event,
                tool_result=group.tool_result,
                command_start=group.command_start,
                command_end=group.command_end,
                tool_call_payload=payload,
                tool_result_payload=group.tool_result_payload,
                command_start_payload=group.command_start_payload,
                command_end_payload=group.command_end_payload,
                first_index=group.first_index,
            )
        elif event.event_kind == "tool_result":
            group = _MergedGroup(
                tool_call=group.tool_call,
                tool_result=event,
                command_start=group.command_start,
                command_end=group.command_end,
                tool_call_payload=group.tool_call_payload,
                tool_result_payload=payload,
                command_start_payload=group.command_start_payload,
                command_end_payload=group.command_end_payload,
                first_index=group.first_index,
            )
        elif event.event_kind == "command_start":
            group = _MergedGroup(
                tool_call=group.tool_call,
                tool_result=group.tool_result,
                command_start=event,
                command_end=group.command_end,
                tool_call_payload=group.tool_call_payload,
                tool_result_payload=group.tool_result_payload,
                command_start_payload=payload,
                command_end_payload=group.command_end_payload,
                first_index=group.first_index,
            )
        else:
            group = _MergedGroup(
                tool_call=group.tool_call,
                tool_result=group.tool_result,
                command_start=group.command_start,
                command_end=event,
                tool_call_payload=group.tool_call_payload,
                tool_result_payload=group.tool_result_payload,
                command_start_payload=group.command_start_payload,
                command_end_payload=payload,
                first_index=group.first_index,
            )
        groups[key] = group
        merged[group.first_index] = _build_merged_call_event(group)

    return [item for item in merged if item is not None]


def _encode_page_token(state: _CardPageState) -> str:
    raw = json.dumps(
        {
            "project_id": state.project_id,
            "execution_id": state.execution_id,
            "event_kinds_mode": state.event_kinds_mode,
            "event_kinds": list(state.event_kinds),
            "offset": state.offset,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_page_token(
    token: str | None,
    *,
    project_id: str,
    execution_id: str,
    event_kinds_mode: str,
    event_kinds: tuple[str, ...],
) -> _CardPageState:
    if not token:
        return _CardPageState(
            project_id=project_id,
            execution_id=execution_id,
            event_kinds_mode=event_kinds_mode,
            event_kinds=event_kinds,
            offset=0,
        )
    try:
        padded = token + ("=" * (-len(token) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        state = _CardPageState(
            project_id=str(payload.get("project_id") or ""),
            execution_id=str(payload.get("execution_id") or ""),
            event_kinds_mode=str(payload.get("event_kinds_mode") or "include"),
            event_kinds=tuple(str(item) for item in (payload.get("event_kinds") or [])),
            offset=max(0, int(payload.get("offset") or 0)),
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("invalid page token") from None
    if (
        state.project_id != project_id
        or state.execution_id != execution_id
        or state.event_kinds_mode != event_kinds_mode
        or state.event_kinds != event_kinds
    ):
        raise ValueError("page token does not match query")
    return state


def _page_range_label(cards: list[LlmEventCard]) -> str:
    if not cards:
        return ""
    first = cards[0].sequence
    last = cards[-1].sequence
    return f"#{first}-#{last}" if first and last else ""


def _list_filtered_events(
    conn: Any,
    project_id: str,
    *,
    execution_id: str | None,
    event_kinds: list[str] | None,
) -> tuple[list[Any], int]:
    rows_result = LlmEventRepository(conn).list_incremental_events(
        project_id,
        execution_id=execution_id,
        after=0,
        limit=1000000,
        event_kinds=event_kinds,
    )
    return [row_to_event(row) for row in rows_result.rows], rows_result.last_sequence


def list_event_cards(
    conn: Any,
    project_id: str,
    *,
    execution_id: str | None = None,
    page_size: int = 20,
    page_token: str | None = None,
    event_kinds: list[str] | tuple[str, ...] | None = None,
) -> EventCardPageResponse:
    allowed_kinds = normalize_event_kind_filter(event_kinds)
    event_kinds_mode = "all" if allowed_kinds is None else "include"
    normalized_execution_id = execution_id or ""
    state = _decode_page_token(
        page_token,
        project_id=project_id,
        execution_id=normalized_execution_id,
        event_kinds_mode=event_kinds_mode,
        event_kinds=tuple(allowed_kinds or []),
    )
    rows, last_sequence = _list_filtered_events(
        conn,
        project_id,
        execution_id=execution_id,
        event_kinds=allowed_kinds,
    )
    cards = merge_event_cards(rows)
    offset = min(state.offset, len(cards))
    next_offset = min(len(cards), offset + max(1, page_size))
    page_cards = cards[offset:next_offset]
    has_next = next_offset < len(cards)
    next_token = None
    if has_next:
        next_token = _encode_page_token(
            _CardPageState(
                project_id=project_id,
                execution_id=normalized_execution_id,
                event_kinds_mode=event_kinds_mode,
                event_kinds=tuple(allowed_kinds or []),
                offset=next_offset,
            )
        )
    return EventCardPageResponse(
        cards=page_cards,
        has_next=has_next,
        next_page_token=next_token,
        page_range_label=_page_range_label(page_cards),
        last_sequence=last_sequence,
    )
