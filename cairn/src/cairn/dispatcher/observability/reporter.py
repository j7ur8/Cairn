from __future__ import annotations

import logging
import uuid

from cairn.dispatcher.config import ObservabilityConfig
from cairn.dispatcher.observability.buffer import OutputBuffer
from cairn.dispatcher.observability.redaction import redact_content
from cairn.dispatcher.observability.trace import TraceEvent
from cairn.dispatcher.protocol.client import CairnClient

LOG = logging.getLogger(__name__)


class ExecutionReporter:
    def __init__(
        self,
        client: CairnClient,
        settings: ObservabilityConfig,
        *,
        project_id: str,
        intent_id: str | None,
        task_type: str,
        worker: str,
    ):
        self.client = client
        self.settings = settings
        self.project_id = project_id
        self.intent_id = intent_id
        self.task_type = task_type
        self.worker = worker
        self.execution_id = uuid.uuid4().hex
        self.started = False
        self.dropped_regular_output = False
        self.produced_fact_id: str | None = None
        self.created_intent_ids: list[str] | None = None
        self._bytes_written = 0
        self._buffer = OutputBuffer(settings.flush_interval_ms, settings.flush_max_bytes)

    @classmethod
    def disabled(cls) -> "DisabledExecutionReporter":
        return DisabledExecutionReporter()

    def start(self) -> None:
        if not self.settings.enabled:
            return
        response = self.client.create_llm_execution(
            self.project_id,
            self.execution_id,
            intent_id=self.intent_id,
            task_type=self.task_type,
            worker=self.worker,
        )
        self.started = response.ok
        if not response.ok:
            LOG.debug(
                "observability execution start failed project=%s execution=%s status=%s",
                self.project_id,
                self.execution_id,
                response.status_code,
            )

    def emit_prompt(self, phase: str, content: str) -> None:
        if not self.settings.record_prompts:
            return
        self._emit(phase, "prompt", "prompt", content)

    def emit_output(self, phase: str, stream: str, content: str) -> None:
        if stream == "stdout" and not self.settings.record_stdout:
            return
        if stream == "stderr" and not self.settings.record_stderr:
            return
        if self.dropped_regular_output:
            return
        for item in self._buffer.add(phase, stream, content):
            self._emit(item.phase, item.stream, item.stream, item.content, regular_output=True)

    def emit_trace_event(self, event: TraceEvent) -> None:
        self.flush()
        self._emit(event.phase, event.kind, event.stream, event.formatted_content())

    def flush(self) -> None:
        for item in self._buffer.flush():
            self._emit(item.phase, item.stream, item.stream, item.content, regular_output=True)

    def emit_result(
        self,
        phase: str,
        content: str,
        *,
        produced_fact_id: str | None = None,
        created_intent_ids: list[str] | None = None,
    ) -> None:
        self.flush()
        self._emit(phase, "model_response", "result", content)
        if produced_fact_id or created_intent_ids:
            if produced_fact_id:
                self.produced_fact_id = produced_fact_id
            if created_intent_ids:
                existing = self.created_intent_ids or []
                self.created_intent_ids = [*existing, *created_intent_ids]

    def emit_error(self, phase: str, event_kind: str, content: str) -> None:
        self.flush()
        self._emit(phase, event_kind, "error", content)

    def finish(
        self,
        process_state: str,
        *,
        returncode: int | None = None,
        timed_out: bool = False,
        error_kind: str | None = None,
        produced_fact_id: str | None = None,
        created_intent_ids: list[str] | None = None,
    ) -> None:
        if not self.settings.enabled or not self.started:
            return
        self.flush()
        self._emit(
            "finish",
            "process_end",
            "system",
            f"process_state={process_state} returncode={returncode} timed_out={timed_out} error_kind={error_kind or ''}",
        )
        response = self.client.finish_llm_execution(
            self.project_id,
            self.execution_id,
            process_state=process_state,
            returncode=returncode,
            timed_out=timed_out,
            error_kind=error_kind,
            produced_fact_id=produced_fact_id or self.produced_fact_id,
            created_intent_ids=created_intent_ids or self.created_intent_ids,
        )
        if not response.ok:
            LOG.debug(
                "observability execution finish failed project=%s execution=%s status=%s",
                self.project_id,
                self.execution_id,
                response.status_code,
            )

    def _emit(self, phase: str, event_kind: str, stream: str, content: str, *, regular_output: bool = False) -> None:
        if not self.settings.enabled or not self.started:
            return
        content, _ = redact_content(content, self.settings.redaction_patterns)
        byte_count = len(content.encode("utf-8"))
        if regular_output and self._bytes_written + byte_count > self.settings.max_bytes_per_execution:
            self.dropped_regular_output = True
            self._emit(
                phase,
                "error",
                "system",
                "Execution log byte limit reached; further stdout/stderr output is not recorded.",
            )
            return
        self._bytes_written += byte_count
        response = self.client.create_llm_event(
            self.project_id,
            self.execution_id,
            phase=phase,
            event_kind=event_kind,
            stream=stream,
            content=content,
        )
        if not response.ok:
            LOG.debug(
                "observability event write failed project=%s execution=%s phase=%s status=%s",
                self.project_id,
                self.execution_id,
                phase,
                response.status_code,
            )


class DisabledExecutionReporter:
    execution_id = ""

    def start(self) -> None:
        pass

    def emit_prompt(self, phase: str, content: str) -> None:
        pass

    def emit_output(self, phase: str, stream: str, content: str) -> None:
        pass

    def emit_trace_event(self, event: TraceEvent) -> None:
        pass

    def emit_result(
        self,
        phase: str,
        content: str,
        *,
        produced_fact_id: str | None = None,
        created_intent_ids: list[str] | None = None,
    ) -> None:
        pass

    def emit_error(self, phase: str, event_kind: str, content: str) -> None:
        pass

    def flush(self) -> None:
        pass

    def finish(
        self,
        process_state: str,
        *,
        returncode: int | None = None,
        timed_out: bool = False,
        error_kind: str | None = None,
        produced_fact_id: str | None = None,
        created_intent_ids: list[str] | None = None,
    ) -> None:
        pass
