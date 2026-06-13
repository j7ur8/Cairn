from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from cairn.dispatcher.protocol.client import CairnClient

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class EventBatch:
    events: list[dict[str, str]]


@dataclass(slots=True)
class FinishRequest:
    process_state: str
    returncode: int | None
    timed_out: bool
    error_kind: str | None
    produced_fact_id: str | None
    created_intent_ids: list[str] | None


class ObservabilitySink:
    def __init__(
        self,
        client: CairnClient,
        *,
        project_id: str,
        execution_id: str,
        max_queue_items: int = 128,
    ):
        self.client = client
        self.project_id = project_id
        self.execution_id = execution_id
        self._queue: queue.Queue[EventBatch | FinishRequest | None] = queue.Queue(maxsize=max_queue_items)
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"cairn-observability-{execution_id[:8]}",
            daemon=True,
        )
        self.dropped_events = 0
        self._thread.start()

    def enqueue_events(self, events: list[dict[str, str]]) -> None:
        if not events or self._closed.is_set():
            return
        try:
            self._queue.put_nowait(EventBatch(events))
        except queue.Full:
            self.dropped_events += len(events)
            LOG.debug(
                "observability queue full project=%s execution=%s dropped=%s",
                self.project_id,
                self.execution_id,
                len(events),
            )

    def enqueue_finish(self, finish: FinishRequest) -> None:
        if self._closed.is_set():
            return
        try:
            self._queue.put_nowait(finish)
        except queue.Full:
            LOG.debug(
                "observability queue full dropping finish project=%s execution=%s",
                self.project_id,
                self.execution_id,
            )

    def close(self, *, drain_timeout: float = 2.0) -> None:
        if self._closed.is_set():
            return
        deadline = time.monotonic() + drain_timeout
        while time.monotonic() < deadline and not self._queue.empty():
            time.sleep(0.01)
        self._closed.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        remaining = max(0.0, deadline - time.monotonic())
        self._thread.join(timeout=remaining)

    def _run(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._closed.is_set():
                    return
                continue
            try:
                if item is None:
                    return
                if isinstance(item, EventBatch):
                    self._write_events(item.events)
                else:
                    self._finish(item)
            finally:
                self._queue.task_done()

    def _write_events(self, events: list[dict[str, str]]) -> None:
        response = self.client.create_llm_events(
            self.project_id,
            self.execution_id,
            events,
        )
        if not response.ok:
            self.dropped_events += len(events)
            LOG.debug(
                "observability event batch write failed project=%s execution=%s count=%s status=%s",
                self.project_id,
                self.execution_id,
                len(events),
                response.status_code,
            )

    def _finish(self, finish: FinishRequest) -> None:
        response = self.client.finish_llm_execution(
            self.project_id,
            self.execution_id,
            process_state=finish.process_state,
            returncode=finish.returncode,
            timed_out=finish.timed_out,
            error_kind=finish.error_kind,
            produced_fact_id=finish.produced_fact_id,
            created_intent_ids=finish.created_intent_ids,
        )
        if not response.ok:
            LOG.debug(
                "observability execution finish failed project=%s execution=%s status=%s",
                self.project_id,
                self.execution_id,
                response.status_code,
            )
