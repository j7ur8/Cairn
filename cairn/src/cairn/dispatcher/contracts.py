from __future__ import annotations

import logging
import math
from typing import Any

from cairn.dispatcher.output_parser import extract_json_objects

DEFAULT_INTENT_PRIORITY = 0.5
LOG = logging.getLogger(__name__)
PROTOCOL_SENTINEL = "32173462130721312360912"
REASON_COMPLETE_SENTINEL = PROTOCOL_SENTINEL
REASON_INTENTS_SENTINEL = "84913462130721312360912"
REASON_NOOP_SENTINEL = "00003462130721312360912"
REASON_SENTINELS = (
    REASON_COMPLETE_SENTINEL,
    REASON_INTENTS_SENTINEL,
    REASON_NOOP_SENTINEL,
)


def parse_json_output(stdout: str) -> dict[str, Any]:
    objects = _candidate_protocol_payloads(stdout)
    for payload in objects:
        normalized = _normalize_protocol_payload(payload)
        if normalized is not None:
            return normalized
    raise ValueError("no JSON object found in output")


def parse_sentinel_fact_output(stdout: str) -> str:
    facts = _sentinel_text_segments(stdout)
    if not facts:
        raise ValueError("no sentinel fact found in output")
    if len(facts) > 1:
        raise ValueError("multiple sentinel facts found in output")
    description = facts[0].strip()
    if not description:
        raise ValueError("sentinel fact must not be empty")
    if _looks_like_json_text(description):
        raise ValueError("sentinel fact must be plain text, not JSON")
    return description


def parse_reason_output(stdout: str) -> dict[str, Any]:
    segments = _reason_sentinel_segments(stdout)
    if not segments:
        return parse_json_output(stdout)
    if len(segments) > 1:
        raise ValueError("multiple reason sentinel payloads found in output")
    marker, content = segments[0]
    payload = parse_json_output(content)
    _validate_reason_marker_payload(marker, payload)
    return payload


def _sentinel_text_segments(text: str) -> list[str]:
    facts: list[str] = []
    start = 0
    while True:
        left = text.find(PROTOCOL_SENTINEL, start)
        if left < 0:
            return facts
        content_start = left + len(PROTOCOL_SENTINEL)
        right = text.find(PROTOCOL_SENTINEL, content_start)
        if right < 0:
            return facts
        facts.append(text[content_start:right])
        start = right + len(PROTOCOL_SENTINEL)


def _reason_sentinel_segments(text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for marker in REASON_SENTINELS:
        start = 0
        while True:
            left = text.find(marker, start)
            if left < 0:
                break
            content_start = left + len(marker)
            right = text.find(marker, content_start)
            if right < 0:
                raise ValueError(f"unterminated reason sentinel {marker}")
            segments.append((marker, text[content_start:right]))
            start = right + len(marker)
    return segments


def _validate_reason_marker_payload(marker: str, payload: dict[str, Any]) -> None:
    if payload.get("accepted") is False:
        raise ValueError("reason sentinel payload must be accepted")
    if payload.get("accepted") is not True:
        raise ValueError("accepted must be true or false")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    has_complete = "complete" in data
    has_intents = "intents" in data
    has_singular_intent = "intent" in data
    if marker == REASON_COMPLETE_SENTINEL:
        if not has_complete or has_intents or has_singular_intent:
            raise ValueError("complete sentinel requires data.complete only")
        return
    if marker == REASON_INTENTS_SENTINEL:
        if has_complete or has_singular_intent or not has_intents:
            raise ValueError("intents sentinel requires data.intents only")
        return
    if marker == REASON_NOOP_SENTINEL:
        if data:
            raise ValueError("noop sentinel requires empty data")
        return
    raise ValueError(f"unsupported reason sentinel {marker}")


def _looks_like_json_text(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") or stripped.startswith("[")


def _candidate_protocol_payloads(stdout: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for payload in extract_json_objects(stdout):
        candidates.append(payload)
        nested = _extract_nested_agent_message(payload)
        if nested is not None:
            candidates.append(nested)
    return candidates


def _extract_nested_agent_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    message: Any = None
    payload_type = payload.get("type")
    item = payload.get("item")
    body = payload.get("payload")
    if payload_type == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
        message = item.get("text") or item.get("message")
    elif payload_type == "event_msg" and isinstance(body, dict) and body.get("type") == "agent_message":
        message = body.get("message")
    elif payload_type == "response_item" and isinstance(body, dict) and body.get("type") == "message":
        message = _extract_response_item_text(body.get("content"))
    if not isinstance(message, str) or not message.strip():
        return None
    for nested in extract_json_objects(message):
        normalized = _normalize_protocol_payload(nested)
        if normalized is not None:
            return normalized
    return None


def _extract_response_item_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts).strip()


def _normalize_protocol_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    accepted = payload.get("accepted")
    if accepted is False:
        return payload
    if accepted is True:
        return payload
    if _looks_like_protocol_data(payload):
        return {"accepted": True, "data": payload}
    return None


def _looks_like_protocol_data(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    keys = set(payload)
    if keys == {"fact"}:
        return isinstance(payload.get("fact"), dict)
    if keys == {"fact", "complete"}:
        return isinstance(payload.get("fact"), dict)
    if keys == {"description"}:
        return isinstance(payload.get("description"), str)
    if keys == {"complete"}:
        complete = payload.get("complete")
        return isinstance(complete, dict) and "from" in complete and "description" in complete
    if keys == {"intent"}:
        intent = payload.get("intent")
        return isinstance(intent, dict) and "from" in intent and "description" in intent
    if keys == {"intents"}:
        return isinstance(payload.get("intents"), list)
    return False


def validate_reason_payload(
    payload: dict[str, Any], open_intents_empty: bool, max_intents: int,
) -> tuple[str, dict[str, Any] | list[dict[str, Any]] | None]:
    if payload.get("accepted") is False:
        return "rejected", None
    if payload.get("accepted") is not True:
        raise ValueError("accepted must be true or false")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    complete = data.get("complete")
    intents = data.get("intents")
    # Accept the singular form because some models still emit it even though
    # the prompt asks for an intents array.
    if intents is None:
        singular = data.get("intent")
        if isinstance(singular, dict):
            intents = [singular]
    if complete is not None:
        if intents is not None:
            raise ValueError("complete and intents cannot coexist")
        if not isinstance(complete, dict) or "from" not in complete or "description" not in complete:
            raise ValueError("invalid complete payload")
        return "complete", complete
    if intents is not None:
        if not isinstance(intents, list):
            raise ValueError("intents must be an array")
        for i, intent in enumerate(intents):
            if not isinstance(intent, dict) or "from" not in intent or "description" not in intent:
                raise ValueError(f"invalid intent at index {i}")
            _normalize_reason_intent(intent, i)
        if not intents and open_intents_empty:
            raise ValueError("intents must not be empty when open_intents is empty")
        intents = intents[:max_intents]
        if not intents:
            return "noop", None
        return "intents", intents
    if open_intents_empty:
        raise ValueError("intents is required when open_intents is empty")
    return "noop", None


def _normalize_reason_intent(intent: dict[str, Any], index: int) -> None:
    priority_score = intent.get("priority_score", DEFAULT_INTENT_PRIORITY)
    if isinstance(priority_score, bool) or not isinstance(priority_score, int | float):
        raise ValueError(f"invalid priority_score at intent index {index}")
    priority = float(priority_score)
    if not math.isfinite(priority) or priority < 0.0 or priority > 1.0:
        raise ValueError(f"priority_score out of range at intent index {index}")
    intent["priority_score"] = priority

    tags = intent.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError(f"invalid tags at intent index {index}")
    intent["tags"] = [tag.strip() for tag in tags if tag.strip()]

    intent_kind = intent.get("intent_kind")
    if intent_kind is not None and not isinstance(intent_kind, str):
        raise ValueError(f"invalid intent_kind at intent index {index}")
    intent["intent_kind"] = intent_kind.strip() if isinstance(intent_kind, str) and intent_kind.strip() else None

    score_reason = intent.get("score_reason")
    if score_reason is not None and not isinstance(score_reason, str):
        raise ValueError(f"invalid score_reason at intent index {index}")
    intent["score_reason"] = score_reason.strip() if isinstance(score_reason, str) and score_reason.strip() else None

    branch_key = intent.get("branch_key")
    if branch_key is not None and not isinstance(branch_key, str):
        raise ValueError(f"invalid branch_key at intent index {index}")
    if isinstance(branch_key, str):
        branch_key = branch_key.strip()
        if not branch_key:
            raise ValueError(f"empty branch_key at intent index {index}")
        _warn_if_non_leaf_branch_key(branch_key, index)
    intent["branch_key"] = branch_key

    branch_depth = intent.get("branch_depth", 0)
    if isinstance(branch_depth, bool) or not isinstance(branch_depth, int):
        raise ValueError(f"invalid branch_depth at intent index {index}")
    if branch_depth < 0:
        raise ValueError(f"branch_depth out of range at intent index {index}")
    intent["branch_depth"] = branch_depth

    expected_value = intent.get("expected_value")
    if expected_value is not None:
        if isinstance(expected_value, bool) or not isinstance(expected_value, int | float):
            raise ValueError(f"invalid expected_value at intent index {index}")
        value = float(expected_value)
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise ValueError(f"expected_value out of range at intent index {index}")
        expected_value = value
    intent["expected_value"] = expected_value


def _warn_if_non_leaf_branch_key(branch_key: str, index: int) -> None:
    parts = [part.strip() for part in branch_key.split(".") if part.strip()]
    if len(parts) >= 3:
        return
    LOG.warning(
        "reason intent index=%s emitted non-leaf branch_key=%r; expected at least area.family.method",
        index,
        branch_key,
    )


def validate_explore_payload(payload: dict[str, Any]) -> tuple[str, str | None]:
    if payload.get("accepted") is False:
        return "rejected", None
    if payload.get("accepted") is not True:
        raise ValueError("accepted must be true or false")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description is required")
    return "fact", description.strip()
