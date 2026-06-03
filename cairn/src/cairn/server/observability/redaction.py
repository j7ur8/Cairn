from __future__ import annotations

import re

BUILTIN_PATTERNS = [
    r"(?i)(OPENAI_API_KEY|ANTHROPIC_AUTH_TOKEN|[A-Z0-9_]*(?:API_KEY|AUTH_TOKEN))\s*[:=]\s*['\"]?[^'\"\s,}]+",
    r"""(?i)(?<![A-Za-z_])(Authorization"?\s*:\s*"?Bearer"?\s+)[A-Za-z0-9._~+/=-]+""",
]


def redact_content(content: str, patterns: list[str]) -> tuple[str, bool]:
    redacted = False
    output = content
    for pattern in [*BUILTIN_PATTERNS, *patterns]:
        if not pattern:
            continue
        try:
            next_output = re.sub(pattern, _replacement, output)
        except re.error:
            continue
        if next_output != output:
            redacted = True
            output = next_output
    return output, redacted


def _replacement(match: re.Match[str]) -> str:
    if match.lastindex:
        prefix = match.group(1)
        if prefix.lower().startswith("authorization"):
            return f"{prefix}[REDACTED]"
        return f"{prefix}=[REDACTED]"
    return "[REDACTED]"


def truncate_content(content: str, max_event_bytes: int) -> tuple[str, bool]:
    encoded = content.encode("utf-8")
    if len(encoded) <= max_event_bytes:
        return content, False
    truncated = encoded[:max_event_bytes].decode("utf-8", errors="ignore")
    return truncated, True
