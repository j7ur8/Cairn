from __future__ import annotations

import logging
import re

LOG = logging.getLogger(__name__)
MAX_REDACT_INPUT_BYTES = 4 * 1024 * 1024

BUILTIN_PATTERNS = [
    r"(?i)(OPENAI_API_KEY|ANTHROPIC_AUTH_TOKEN|[A-Z0-9_]*(?:API_KEY|AUTH_TOKEN))\s*[:=]\s*['\"]?[^'\"\s,}]+",
    r"""(?i)(?<![A-Za-z_])(Authorization"?\s*:\s*"?Bearer"?\s+)[A-Za-z0-9._~+/=-]+""",
    r"sk-[A-Za-z0-9][A-Za-z0-9_-]{15,}",
    # Proxy secrets: covers HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / SOCKS5_PROXY
    # env values that may contain `user:pass@host:port` (basic-auth-in-URL).
    # The whole `KEY=VALUE` is redacted, including credentials, so a single
    # regex replaces the entire env-var assignment without leaving the auth
    # tuple in the redacted output.
    r"(?i)((?:HTTP|HTTPS|ALL|SOCKS5)_PROXY|[A-Z0-9_]*PROXY_(?:PASSWORD|URL))\s*[:=]\s*[^\s,}]+",
]


def redact_content(content: str, patterns: list[str]) -> tuple[str, bool]:
    if len(content.encode("utf-8", errors="ignore")) > MAX_REDACT_INPUT_BYTES:
        LOG.warning(
            "skip redaction because content is too large bytes=%s max=%s",
            len(content.encode("utf-8", errors="ignore")),
            MAX_REDACT_INPUT_BYTES,
        )
        return content, False
    output = content
    redacted = False
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
