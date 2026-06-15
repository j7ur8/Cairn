from __future__ import annotations

import socket
import urllib.parse
from typing import Any

from cairn.dispatcher.capability_constants import CHROME_DEVTOOLS_PROBE_TYPE, HOST_DOCKER_INTERNAL


def host_netloc(host: str, port: int | None) -> str:
    netloc_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{netloc_host}:{port}" if port is not None else netloc_host


def resolve_host_alias_url(url: str) -> tuple[str, str | None]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host or host.lower() != HOST_DOCKER_INTERNAL:
        return url, None
    try:
        resolved = socket.gethostbyname(host)
    except OSError as exc:
        return url, f"resolve {host} failed: {type(exc).__name__}: {exc}"
    netloc = host_netloc(resolved, parsed.port)
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc)), None


def is_chrome_devtools_probe(probe_config: dict[str, Any] | None) -> bool:
    if not isinstance(probe_config, dict):
        return False
    return str(probe_config.get("type") or "").strip() == CHROME_DEVTOOLS_PROBE_TYPE
