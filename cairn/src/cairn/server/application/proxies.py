from __future__ import annotations

from typing import Any

from cairn.server.repositories.projects import ProjectRepository


def detach_proxy_from_projects(conn: Any, proxy_id: str) -> None:
    ProjectRepository(conn).clear_proxy(proxy_id)
