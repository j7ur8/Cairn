from __future__ import annotations

from collections.abc import Callable


def proxy_environment(
    proxy_resolver: Callable[[str], dict[str, str] | None] | None,
    project_id: str,
) -> dict[str, str]:
    if proxy_resolver is None:
        return {}
    resolved = proxy_resolver(project_id) or {}
    return dict(resolved)
