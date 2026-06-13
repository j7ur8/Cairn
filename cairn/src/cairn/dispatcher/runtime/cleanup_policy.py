from __future__ import annotations


def needs_cleanup_for_action(state: str | None, action: str) -> bool:
    if state is None:
        return False
    if action == "remove":
        return True
    return state == "running"
