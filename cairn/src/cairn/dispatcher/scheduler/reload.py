from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cairn.dispatcher.prompts.validation import validate_prompt_resources
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.shared.config import DispatchConfig

LOG = logging.getLogger(__name__)


class DispatcherReloader:
    def __init__(self, loop: object, config_path: Path) -> None:
        self.loop = loop
        self.config_path = config_path
        self.lock = threading.Lock()

    def reload_from_health_server(self, authorization: str | None) -> dict[str, object]:
        loop = self.loop
        expected = loop.config.system.auth.dispatcher_api_token
        if expected and authorization != f"Bearer {expected}":
            raise PermissionError("invalid reload token")
        with self.lock:
            next_config = DispatchConfig.load(self.config_path)
            validate_prompt_resources(next_config.runtime.prompt_group)
            next_container_manager = ContainerManager(
                next_config.container,
                proxy_resolver=loop.project_context.resolve_proxy_env,
            )
            old_container_manager = loop.container_manager
            old_executor = loop.executor
            old_cleanup_executor = loop.cleanup.refresh(
                next_container_manager,
                max_workers=next_config.runtime.max_workers,
            )
            loop.config = next_config
            loop.client.close()
            loop.client._base_url = next_config.server_url.rstrip("/")  # noqa: SLF001 - reloads existing client wiring.
            loop.container_manager = next_container_manager
            if hasattr(loop, "scheduler_services"):
                loop.scheduler_services.refresh(
                    config=loop.config,
                    client=loop.client,
                    container_manager=loop.container_manager,
                )
            loop.health.refresh(
                config=loop.config,
                client=loop.client,
                container_manager=loop.container_manager,
            )
            loop.execution_configs.client = loop.client
            loop.replay.client = loop.client
            loop.executor = ThreadPoolExecutor(max_workers=next_config.runtime.max_workers)
            loop.project_caches.clear_all()
            loop._ai_overlay_cache.invalidate()
            loop.runtime.clear_backoff()
            loop.submitter.refresh(
                config=loop.config,
                client=loop.client,
                container_manager=loop.container_manager,
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
            try:
                old_container_manager.close()
            finally:
                old_executor.shutdown(wait=False, cancel_futures=False)
                old_cleanup_executor.shutdown(wait=False, cancel_futures=False)
        LOG.info("dispatcher config reloaded workers=%s", len(loop.config.workers))
        return {"ok": True, "workers": len(loop.config.workers)}
