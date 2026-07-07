from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING

from cairn.shared.contracts import ProjectSummary

if TYPE_CHECKING:
    from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager
    from cairn.dispatcher.runtime.containers import ContainerManager
    from cairn.dispatcher.runtime.tool_sidecar import ToolSidecarManager

LOG = logging.getLogger(__name__)


class ContainerCleanupCoordinator:
    """Own dispatcher container cleanup state.

    The scheduler loop decides when a tick happens. This object owns the
    secondary cleanup executor and the bookkeeping needed to avoid queuing
    duplicate cleanup jobs for the same container.
    """

    def __init__(
        self,
        container_manager: ContainerManager,
        *,
        cloak_sidecar_manager: CloakSidecarManager | None = None,
        tool_sidecar_manager: ToolSidecarManager | None = None,
        max_workers: int,
    ) -> None:
        self.container_manager = container_manager
        self.cloak_sidecar_manager = cloak_sidecar_manager
        self.tool_sidecar_manager = tool_sidecar_manager
        self.executor = _cleanup_executor(max_workers)
        self.futures: dict[Future[bool], tuple[str, str | None, str | None]] = {}
        self.pending: set[str] = set()
        self.inactive_done: dict[str, str] = {}

    def refresh(
        self,
        container_manager: ContainerManager,
        *,
        cloak_sidecar_manager: CloakSidecarManager | None = None,
        tool_sidecar_manager: ToolSidecarManager | None = None,
        max_workers: int,
    ) -> ThreadPoolExecutor:
        old_executor = self.executor
        self.container_manager = container_manager
        self.cloak_sidecar_manager = cloak_sidecar_manager
        self.tool_sidecar_manager = tool_sidecar_manager
        self.executor = _cleanup_executor(max_workers)
        self.futures.clear()
        self.pending.clear()
        self.inactive_done.clear()
        return old_executor

    def shutdown(self, *, wait: bool, cancel_futures: bool = False) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def is_pending(self, container_name: str) -> bool:
        return container_name in self.pending

    def queue_for_projects(self, summaries: list[ProjectSummary]) -> None:
        self._queue_completed(summaries)
        self._queue_stopped(summaries)
        self._queue_orphans(summaries)

    def reap(self) -> None:
        done = [future for future in self.futures if future.done()]
        for future in done:
            name, project_id, target_status = self.futures.pop(future)
            for pending_name in name.split(","):
                self.pending.discard(pending_name)
            try:
                success = future.result()
                if success and project_id is not None and target_status in ("completed", "stopped"):
                    self.inactive_done[project_id] = target_status
                elif project_id is not None:
                    self.inactive_done.pop(project_id, None)
            except Exception:
                if project_id is not None:
                    self.inactive_done.pop(project_id, None)
                LOG.exception("container cleanup failed container=%s", name)

    def refresh_active_projects(self, summaries: list[ProjectSummary]) -> None:
        inactive_status_by_id = {summary.id: summary.status for summary in summaries if summary.status != "active"}
        for project_id, status in list(self.inactive_done.items()):
            current_status = inactive_status_by_id.get(project_id)
            if current_status != status:
                self.inactive_done.pop(project_id, None)

    def _queue_completed(self, summaries: list[ProjectSummary]) -> None:
        for summary in summaries:
            if summary.status != "completed":
                continue
            if self.inactive_done.get(summary.id) == summary.status:
                continue
            container_name = self.container_manager.container_name(summary.id)
            if container_name in self.pending:
                continue
            if not self.container_manager.needs_completed_cleanup(summary.id):
                self.inactive_done[summary.id] = summary.status
                self._queue_cloak_sidecar(summary.id, target_status=summary.status, remove=False)
                self._queue_tool_sidecars(summary.id, target_status=summary.status)
                continue
            future = self.executor.submit(self.container_manager.cleanup_completed, summary.id)
            self.futures[future] = (container_name, summary.id, summary.status)
            self.pending.add(container_name)
            self._queue_cloak_sidecar(summary.id, target_status=summary.status, remove=False)
            self._queue_tool_sidecars(summary.id, target_status=summary.status)

    def _queue_stopped(self, summaries: list[ProjectSummary]) -> None:
        for summary in summaries:
            if summary.status != "stopped":
                continue
            if self.inactive_done.get(summary.id) == summary.status:
                continue
            container_name = self.container_manager.container_name(summary.id)
            if container_name in self.pending:
                continue
            if not self.container_manager.needs_stopped_cleanup(summary.id):
                self.inactive_done[summary.id] = summary.status
                self._queue_cloak_sidecar(summary.id, target_status=summary.status, remove=True)
                self._queue_tool_sidecars(summary.id, target_status=summary.status)
                continue
            future = self.executor.submit(self.container_manager.cleanup_stopped, summary.id)
            self.futures[future] = (container_name, summary.id, summary.status)
            self.pending.add(container_name)
            self._queue_cloak_sidecar(summary.id, target_status=summary.status, remove=True)
            self._queue_tool_sidecars(summary.id, target_status=summary.status)

    def _queue_orphans(self, summaries: list[ProjectSummary]) -> None:
        expected_container_names = {self.container_manager.container_name(summary.id) for summary in summaries}
        expected_cloak_container_names: set[str] = set()
        if self.cloak_sidecar_manager is not None:
            from cairn.dispatcher.runtime.cloak_sidecar import cloak_container_name

            expected_cloak_container_names = {cloak_container_name(summary.id) for summary in summaries}
            expected_cloak_container_names.add(cloak_container_name("probe"))
        expected_tool_sidecar_names: set[str] = set()
        if self.tool_sidecar_manager is not None:
            from cairn.dispatcher.runtime.tool_sidecar import tool_sidecar_name

            expected_tool_sidecar_names = {
                tool_sidecar_name(summary.id, tool)
                for summary in summaries
                for tool in ("kali", "metasploit")
            }
        for container_name in self.container_manager.managed_container_names():
            if container_name in expected_container_names:
                continue
            if container_name in self.pending:
                continue
            if not self.container_manager.needs_orphan_cleanup(container_name):
                continue
            future = self.executor.submit(self.container_manager.cleanup_orphan, container_name)
            self.futures[future] = (container_name, None, None)
            self.pending.add(container_name)
        if self.cloak_sidecar_manager is not None:
            for container_name in self.cloak_sidecar_manager.managed_container_names():
                if container_name in expected_cloak_container_names:
                    continue
                if container_name in self.pending:
                    continue
                future = self.executor.submit(self.cloak_sidecar_manager.cleanup_orphan, container_name)
                self.futures[future] = (container_name, None, None)
                self.pending.add(container_name)
        if self.tool_sidecar_manager is None:
            return
        for container_name in self.tool_sidecar_manager.managed_container_names():
            if container_name in expected_tool_sidecar_names:
                continue
            if container_name in self.pending:
                continue
            future = self.executor.submit(self.tool_sidecar_manager.cleanup_orphan, container_name)
            self.futures[future] = (container_name, None, None)
            self.pending.add(container_name)

    def _queue_cloak_sidecar(self, project_id: str, *, target_status: str, remove: bool) -> None:
        if self.cloak_sidecar_manager is None:
            return
        from cairn.dispatcher.runtime.cloak_sidecar import cloak_container_name

        name = cloak_container_name(project_id)
        if name in self.pending:
            return
        future = self.executor.submit(self.cloak_sidecar_manager.cleanup_project, project_id, remove=remove)
        self.futures[future] = (name, None, target_status)
        self.pending.add(name)

    def _queue_tool_sidecars(self, project_id: str, *, target_status: str) -> None:
        if self.tool_sidecar_manager is None:
            return
        from cairn.dispatcher.runtime.tool_sidecar import tool_sidecar_name

        names = [tool_sidecar_name(project_id, tool) for tool in ("kali", "metasploit")]
        if all(name in self.pending for name in names):
            return
        future = self.executor.submit(self.tool_sidecar_manager.cleanup_project, project_id, remove=True)
        self.futures[future] = (",".join(names), None, target_status)
        for name in names:
            self.pending.add(name)


def _cleanup_executor(max_workers: int) -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=max(1, min(8, max_workers)))
