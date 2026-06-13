from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


def iter_jsonl(text: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON, skipping blank or non-object lines.

    Shared by the claudecode and codex adapters, whose CLIs both emit a
    JSONL event stream on stdout. Malformed lines are dropped rather than
    raising, since worker stdout can interleave non-JSON diagnostics.
    """
    payloads: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def extract_text_parts(content: Any, *, predicate: Callable[[dict[str, Any]], bool] | None = None) -> str:
    """Join the ``text`` fields of a message ``content`` block.

    ``content`` may be a bare string or a list of content items. When a
    ``predicate`` is given, only items for which it returns true contribute
    their text (e.g. claudecode requires ``type == "text"``); without one,
    any item carrying a string ``text`` field contributes (codex behaviour).
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if predicate is not None and not predicate(item):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()
