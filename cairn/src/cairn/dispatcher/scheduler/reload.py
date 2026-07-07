from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairn.dispatcher.prompts.validation import validate_prompt_resources
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.tool_sidecar import ToolSidecarManager
from cairn.shared.config import load_dispatch_config

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeGeneration:
    client: Any
    container_manager: Any
    cloak_sidecar_manager: Any
    tool_sidecar_manager: Any
    executor: ThreadPoolExecutor
    cleanup_executor: ThreadPoolExecutor | None

    def close(self) -> None:
        try:
            self.container_manager.close()
        finally:
            try:
                self.cloak_sidecar_manager.close()
            finally:
                try:
                    self.tool_sidecar_manager.close()
                finally:
                    try:
                        self.client.close()
                    finally:
                        self.executor.shutdown(wait=False, cancel_futures=False)
                        if self.cleanup_executor is not None:
                            self.cleanup_executor.shutdown(wait=False, cancel_futures=False)


class DispatcherReloader:
    # `loop` is typed Any on purpose: the scheduler package must not depend on
    # the loop module (enforced by
    # test_scheduler_collaborators_do_not_depend_on_dispatcher_loop), and
    # reload mutates ~15 loop attributes as a dynamic cross-boundary handle.
    def __init__(self, loop: Any, config_path: Path) -> None:
        self.loop = loop
        self.config_path = config_path
        self.lock = threading.Lock()

    def reload_from_health_server(self, authorization: str | None) -> dict[str, object]:
        loop = self.loop
        expected = loop.config.system.auth.dispatcher_api_token
        if expected and authorization != f"Bearer {expected}":
            raise PermissionError("invalid reload token")
        with self.lock:
            next_config = load_dispatch_config(self.config_path)
            validate_prompt_resources()
            next_client = CairnClient(next_config.server_url, api_token=next_config.system.auth.dispatcher_api_token)
            next_container_manager = ContainerManager(
                next_config.container,
            )
            next_cloak_sidecar_manager = CloakSidecarManager(
                next_config.worker_runtime.cloak_sidecar,
            )
            next_tool_sidecar_manager = ToolSidecarManager(
                next_config.worker_runtime.tool_sidecars,
            )
            next_executor = ThreadPoolExecutor(max_workers=next_config.runtime.max_workers)
            old_container_manager = loop.container_manager
            old_cloak_sidecar_manager = loop.cloak_sidecar_manager
            old_tool_sidecar_manager = loop.tool_sidecar_manager
            old_client = loop.client
            old_executor = loop.executor
            old_cleanup_futures = list(getattr(loop.cleanup, "futures", {}) or {})
            old_cleanup_executor = loop.cleanup.refresh(
                next_container_manager,
                cloak_sidecar_manager=next_cloak_sidecar_manager,
                tool_sidecar_manager=next_tool_sidecar_manager,
                max_workers=next_config.runtime.max_workers,
            )
            loop.config = next_config
            loop.client = next_client
            loop.container_manager = next_container_manager
            loop.cloak_sidecar_manager = next_cloak_sidecar_manager
            loop.tool_sidecar_manager = next_tool_sidecar_manager
            if hasattr(loop, "scheduler_services"):
                loop.scheduler_services.refresh(
                    config=loop.config,
                    client=loop.client,
                    container_manager=loop.container_manager,
                    cloak_sidecar_manager=loop.cloak_sidecar_manager,
                    tool_sidecar_manager=loop.tool_sidecar_manager,
                )
            loop.health.refresh(
                config=loop.config,
                client=loop.client,
                container_manager=loop.container_manager,
            )
            loop.execution_configs.client = loop.client
            loop.execution_configs.clear_all()
            loop.replay.client = loop.client
            loop.executor = next_executor
            loop.project_caches.clear_all()
            loop._ai_overlay_cache.invalidate()
            loop.runtime.clear_backoff()
            loop.submitter.refresh(
                config=loop.config,
                client=loop.client,
                container_manager=loop.container_manager,
                cloak_sidecar_manager=loop.cloak_sidecar_manager,
                tool_sidecar_manager=loop.tool_sidecar_manager,
                executor=loop.executor,
                runtime=loop.runtime,
            )
            loop.ai_worker_selector.refresh(
                config=loop.config,
                worker_unhealthy_until=loop.runtime.worker_unhealthy_until,
                worker_rejected_until=loop.runtime.worker_rejected_until,
            )
            loop.project_context.refresh(
                config=loop.config,
                client=loop.client,
                runtime=loop.runtime,
                ai_worker_selector=loop.ai_worker_selector,
            )
            loop._settings_checked = False
            self._retain_or_close_old_generation(
                RuntimeGeneration(
                    client=old_client,
                    container_manager=old_container_manager,
                    cloak_sidecar_manager=old_cloak_sidecar_manager,
                    tool_sidecar_manager=old_tool_sidecar_manager,
                    executor=old_executor,
                    cleanup_executor=old_cleanup_executor,
                ),
                extra_futures=old_cleanup_futures,
            )
        LOG.info("dispatcher config reloaded workers=%s", len(loop.config.workers))
        return {"ok": True, "workers": len(loop.config.workers)}

    def _retain_or_close_old_generation(
        self,
        generation: RuntimeGeneration,
        *,
        extra_futures: list[Any] | None = None,
    ) -> None:
        runtime = self.loop.runtime
        futures = list(getattr(runtime, "futures", {}) or [])
        futures.extend(extra_futures or [])
        if not futures:
            generation.close()
            return
        pending = set(futures)
        closed = False
        lock = threading.Lock()

        def maybe_close(_future: Any | None = None) -> None:
            nonlocal closed
            with lock:
                if _future is not None:
                    pending.discard(_future)
                if pending or closed:
                    return
                closed = True
            generation.close()

        for future in list(pending):
            future.add_done_callback(maybe_close)
        maybe_close()
