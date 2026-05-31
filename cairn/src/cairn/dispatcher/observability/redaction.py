from __future__ import annotations

import re


def redact_content(content: str, patterns: list[str]) -> tuple[str, bool]:
    output = content
    redacted = False
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
