from __future__ import annotations

from typing import Any

from cairn.dispatcher.output_parser import extract_json_objects


def parse_json_output(stdout: str) -> dict[str, Any]:
    objects = _candidate_protocol_payloads(stdout)
    for payload in objects:
        normalized = _normalize_protocol_payload(payload)
        if normalized is not None:
            return normalized
    raise ValueError("no JSON object found in output")


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
        if not intents and open_intents_empty:
            raise ValueError("intents must not be empty when open_intents is empty")
        intents = intents[:max_intents]
        if not intents:
            return "noop", None
        return "intents", intents
    if open_intents_empty:
        raise ValueError("intents is required when open_intents is empty")
    return "noop", None


def validate_bootstrap_execute_payload(payload: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    if payload.get("accepted") is False:
        return "rejected", None
    if payload.get("accepted") is not True:
        raise ValueError("accepted must be true or false")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("data must be an object")

    fact = data.get("fact")
    if not isinstance(fact, dict):
        raise ValueError("fact is required")
    fact_description = fact.get("description")
    if not isinstance(fact_description, str) or not fact_description.strip():
        raise ValueError("fact.description is required")

    result = {"fact_description": fact_description.strip()}
    complete = data.get("complete")
    if complete is None:
        raise ValueError("complete is required")
    if not isinstance(complete, dict):
        raise ValueError("complete must be an object")
    complete_description = complete.get("description")
    if not isinstance(complete_description, str) or not complete_description.strip():
        raise ValueError("complete.description is required")
    result["complete_description"] = complete_description.strip()
    return "complete", result


def validate_bootstrap_conclude_payload(payload: dict[str, Any]) -> tuple[str, str | None]:
    if payload.get("accepted") is False:
        return "rejected", None
    if payload.get("accepted") is not True:
        raise ValueError("accepted must be true or false")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    if data.get("complete") is not None:
        raise ValueError("complete is not allowed")
    fact = data.get("fact")
    if not isinstance(fact, dict):
        raise ValueError("fact is required")
    fact_description = fact.get("description")
    if not isinstance(fact_description, str) or not fact_description.strip():
        raise ValueError("fact.description is required")
    return "fact", fact_description.strip()


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
