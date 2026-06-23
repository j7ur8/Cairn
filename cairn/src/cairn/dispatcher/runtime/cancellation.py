from __future__ import annotations

import threading
from typing import Protocol


class CancellableProcess(Protocol):
    def cancel(self, reason: str) -> None:
        ...


class TaskCancellation:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: CancellableProcess | None = None
        self._reason: str | None = None

    def attach_process(self, process: CancellableProcess | None) -> None:
        # Snapshot reason under the lock, then act on the local snapshot
        # outside it. Combined with cancel()'s symmetric handoff, this
        # guarantees a cancel requested before the process attaches is still
        # delivered, with no lost-update window. Do not "simplify" by calling
        # process.cancel() inside the lock (it may block) or by reading
        # self._reason after the lock (would reintroduce a race).
        with self._lock:
            self._process = process
            reason = self._reason
        if process is not None and reason is not None:
            process.cancel(reason)

    def cancel(self, reason: str) -> bool:
        with self._lock:
            if self._reason is not None:
                return False
            self._reason = reason
            process = self._process
        if process is not None:
            process.cancel(reason)
        return True

    @property
    def is_cancelled(self) -> bool:
        return self.reason is not None

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason
