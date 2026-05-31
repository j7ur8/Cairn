from __future__ import annotations

import re


def redact_content(content: str, patterns: list[str]) -> tuple[str, bool]:
    redacted = False
    output = content
    for pattern in patterns:
        if not pattern:
            continue
        try:
            next_output = re.sub(pattern, "[REDACTED]", output)
        except re.error:
            continue
        if next_output != output:
            redacted = True
            output = next_output
    return output, redacted


def truncate_content(content: str, max_event_bytes: int) -> tuple[str, bool]:
    encoded = content.encode("utf-8")
    if len(encoded) <= max_event_bytes:
        return content, False
    truncated = encoded[:max_event_bytes].decode("utf-8", errors="ignore")
    return truncated, True
