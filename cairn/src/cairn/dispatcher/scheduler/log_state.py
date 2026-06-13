from __future__ import annotations

import logging


class LogState:
    def __init__(self) -> None:
        self._state: dict[str, tuple[int, str, tuple[object, ...]]] = {}

    def log_changed(self, logger: logging.Logger, scope: str, level: int, message: str, *args: object) -> None:
        state = (level, message, args)
        if self._state.get(scope) == state:
            return
        self._state[scope] = state
        logger.log(level, message, *args)

    def clear(self, scope: str) -> None:
        self._state.pop(scope, None)

    def clear_project(self, project_id: str) -> None:
        prefix = f"project:{project_id}:"
        for scope in list(self._state):
            if scope.startswith(prefix):
                self._state.pop(scope, None)
