from __future__ import annotations

import logging
import os
import time
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import requests

from cairn.dispatcher.config import DispatchConfig, WorkerConfig
from cairn.dispatcher.capabilities import catalog_payload as capability_catalog_payload
from cairn.dispatcher.roles import catalog_payload as role_catalog_payload
from cairn.dispatcher.ai_health import probe_snapshot, run_profile_worker_healthcheck
from cairn.dispatcher.health_server import DispatcherHealthServer, DispatcherHealthState
from cairn.dispatcher.leadership import DispatcherLeader, LeadershipLost
from cairn.dispatcher.models import ReasonCheckpoint, RunningTask
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.startup_healthcheck import format_failure_summary, run_startup_healthchecks
from cairn.dispatcher.scheduler.ai_overlay import AIOverlayCache, compute_ai_overlay
from cairn.dispatcher.scheduler.project_cache import ProjectCaches
from cairn.dispatcher.scheduler.worker_select import choose_worker
from cairn.dispatcher.scheduler.worker_selection import WorkerSelection, select_worker_default
from cairn.dispatcher.tasks.bootstrap import run_bootstrap_task
from cairn.dispatcher.tasks.explore import run_explore_task
from cairn.dispatcher.tasks.reason import run_reason_task
from cairn.observability.metrics import (
    DISPATCHER_INFLIGHT,
    DISPATCHER_OVERFLOW,
    DISPATCHER_STEPDOWN,
    DISPATCHER_TICKS,
    WORKER_UNHEALTHY_SINCE,
)
from cairn.server.models import (
    AiProfile,
    Intent,
    ProjectAiProfileSnapshot,
    ProjectDetail,
    ProjectSummary,
    ProxyConfig,
)

LOG = logging.getLogger(__name__)
UNHEALTHY_RETRY_AFTER_SECONDS = 5
REJECTED_RETRY_AFTER_SECONDS = 5
BOOTSTRAP_INTENT_DESCRIPTION = "bootstrap"
BOOTSTRAP_INTENT_CREATOR = "dispatcher.bootstrap"
REASON_CONSUMED_OUTCOMES = {"success", "complete", "intents", "noop", "blocked"}


# WorkerSelection dataclass moved to scheduler/worker_selection.py.


def _proxy_config_to_env(cfg: ProxyConfig) -> dict[str, str]:
    """Translate a :class:`ProxyConfig` into the env vars a worker container
    needs in order to route traffic through the proxy.

    Behaviour:

    * ``socks5`` -> ``ALL_PROXY`` + ``NO_PROXY`` (socks is the all-protocols
      fallback; ``HTTP_PROXY`` / ``HTTPS_PROXY`` are *not* set because most
      HTTPS libraries will only honour ``ALL_PROXY`` for SOCKS).
    * ``http`` / ``https`` -> ``HTTP_PROXY`` + ``HTTPS_PROXY`` + ``NO_PROXY``.
      ``http`` is used for both so existing tools that read either variable
      get the same value.

    Auth is rendered into the URL as ``user:pass@`` when both are set, or
    ``user@`` when only the username is set. ``NO_PROXY`` always excludes the
    Cairn-internal hostnames so the dispatcher -> server RPC keeps working.
    """
    userpass = ""
    if cfg.username and cfg.password:
        userpass = f"{cfg.username}:{cfg.password}@"
    elif cfg.username:
        userpass = f"{cfg.username}@"
    no_proxy = "localhost,127.0.0.1,cairn-server,cairn"
    if cfg.type == "socks5":
        return {
            "ALL_PROXY": f"socks5://{userpass}{cfg.host}:{cfg.port}",
            "NO_PROXY": no_proxy,
        }
    scheme = "http"
    return {
        "HTTP_PROXY": f"{scheme}://{userpass}{cfg.host}:{cfg.port}",
        "HTTPS_PROXY": f"{scheme}://{userpass}{cfg.host}:{cfg.port}",
        "NO_PROXY": no_proxy,
    }


class DispatcherLoop:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = DispatchConfig.load(config_path)
        self.client = CairnClient(self.config.server)
        self.leader = DispatcherLeader(
            client=self.client,
            ttl_seconds=float(os.environ.get("CAIRN_LEADER_TTL_SECONDS", "15")),
        )
        self._last_tick_at: float | None = None
        self.health_server = DispatcherHealthServer(
            *self._health_addr(),
            state=DispatcherHealthState(
                is_leader=lambda: self.leader.is_leader,
                current_holder=lambda: self.leader.current_holder(),
                last_tick_at=lambda: self._last_tick_at,
            ),
            reload_handler=self._reload_from_health_server,
        )
        self.health_server.start()
        bearer_token_env_keys = tuple(
            mcp.bearer_token_env
            for mcp in self.config.capabilities.mcp_servers
            if mcp.transport == "http" and mcp.bearer_token_env
        )
        self.container_manager = ContainerManager(
            self.config.container,
            bearer_token_env_keys=bearer_token_env_keys,
            proxy_resolver=self._resolve_proxy_env,
        )
        self.executor = ThreadPoolExecutor(max_workers=self.config.runtime.max_workers)
        self.cleanup_executor = ThreadPoolExecutor(max_workers=max(1, min(8, self.config.runtime.max_workers)))
        self.futures: dict[Future[str], RunningTask] = {}
        self.cleanup_futures: dict[Future[bool], tuple[str, str | None, str | None]] = {}
        self.reason_checkpoints: dict[str, ReasonCheckpoint] = {}
        self.runtime_project_ids: set[str] = set()
        self.worker_unhealthy_until: dict[str, float] = {}
        self.worker_rejected_until: dict[tuple[str, str, str], float] = {}
        self._log_state: dict[str, tuple[int, str, tuple[object, ...]]] = {}
        self._cleanup_pending: set[str] = set()
        self._inactive_cleanup_done: dict[str, str] = {}
        self.project_cursor = 0
        self._settings_checked = False
        self._capability_catalog_registered = False
        self._role_catalog_registered = False
        self._startup_healthchecks_checked = False
        self._ai_catalog_synced = False
        # Per-project caches: proxy, AI selection chains, and the
        # fetched ``sk`` values for the profiles in those chains.
        # See :mod:`cairn.dispatcher.scheduler.project_cache` for the
        # invalidation contract.
        self.project_caches = ProjectCaches()
        self._ai_overlay_cache = AIOverlayCache()
        self._reload_lock = threading.Lock()

    def close(self) -> None:
        if self.futures:
            LOG.info(
                "dispatcher shutting down waiting_for_tasks=%s running_projects=%s",
                len(self.futures),
                sorted({task.project_id for task in self.futures.values()}),
            )
        self.executor.shutdown(wait=True)
        self.cleanup_executor.shutdown(wait=True)
        self.container_manager.close()
        try:
            if self.leader._is_leader:
                self.leader.release()
        except Exception:
            LOG.exception("failed to release dispatcher leadership")
        self.client.close()
        self.health_server.stop()

    def run(self, once: bool = False) -> None:
        """Main dispatcher loop.

        Acquires the leader lock (blocking while a sibling dispatcher
        is leader) and runs ticks until either ``once=True`` finishes a
        single tick, a :class:`LeadershipLost` surfaces from
        :meth:`DispatcherLeader.check_health` mid-tick, or the process
        is shut down.

        On :class:`LeadershipLost` we drain the in-flight task
        executors, increment ``DISPATCHER_STEPDOWN`` and re-acquire
        so the next sibling does not have to wait a full
        ``runtime.interval`` to take over.
        """
        try:
            while True:
                try:
                    with self.leader.acquired(retry_interval=self.config.runtime.interval):
                        self._run_leader_iteration(once=once)
                    if once:
                        return
                except LeadershipLost as exc:
                    DISPATCHER_STEPDOWN.labels(reason="lock_lost").inc()
                    LOG.warning("dispatcher stepping down after leadership loss error=%s", exc)
                    self._step_down_executors()
                    if once:
                        return
                    # Loop back: ``acquired()`` will block until the
                    # sibling dispatcher is also done.
                    continue
        finally:
            self.close()

    def _run_leader_iteration(self, *, once: bool) -> None:
        """One tick of work performed under the leader lock."""
        if not self._startup_healthchecks_checked:
            self.run_startup_healthchecks()
            self.leader.heartbeat()
        if not self._settings_checked:
            self._validate_server_settings()
            self._settings_checked = True
            self.leader.heartbeat()
        if not self._capability_catalog_registered:
            self._register_capability_catalog()
            self._capability_catalog_registered = True
            self.leader.heartbeat()
        if not self._role_catalog_registered:
            self._register_role_catalog()
            self._role_catalog_registered = True
            self.leader.heartbeat()
        if not self._ai_catalog_synced:
            self._sync_ai_catalog_from_dispatch_yaml()
            self._ai_catalog_synced = True
            self.leader.heartbeat()
        self._process_ai_profile_check_requests()
        self.leader.heartbeat()
        self._reap_futures()
        self._reap_cleanup_futures()
        summaries = self.client.list_projects()
        self.leader.check_health()
        self._initialize_reason_checkpoints(summaries)
        self._refresh_runtime_projects(summaries)
        self._cancel_inactive_tasks(summaries)
        self._queue_container_cleanups(summaries)
        self._dispatch_available(summaries)
        self._publish_tick_metrics()
        self.leader.heartbeat()
        if once:
            return
        time.sleep(self.config.runtime.interval)

    def _step_down_executors(self) -> None:
        """Cancel in-flight tasks on the main executor so a sibling can
        take over without us submitting duplicate work.

        The cleanup executor is left running because orphan container
        cleanup must keep happening regardless of leader status.
        """
        if not self.futures:
            return
        LOG.info(
            "dispatcher step-down cancelling futures=%s",
            len(self.futures),
        )
        # Best-effort cancellation signal: future.cancel() returns
        # False once the task has already started running, which is
        # fine - those tasks will finish naturally and the next
        # leader will see the work has been claimed.
        for fut in list(self.futures):
            fut.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.futures.clear()
        # Recreate the executor so subsequent ticks (after we
        # re-acquire) can submit new work.
        self.executor = ThreadPoolExecutor(max_workers=self.config.runtime.max_workers)

    def run_startup_healthchecks_only(self) -> None:
        try:
            self.run_startup_healthchecks(show_commands=True)
        finally:
            self.close()

    def run_startup_healthchecks(self, *, show_commands: bool = False) -> None:
        if self._startup_healthchecks_checked:
            return
        self._run_startup_healthchecks(show_commands=show_commands)
        self._startup_healthchecks_checked = True

    def _health_addr(self) -> tuple[str, int]:
        value = os.environ.get("CAIRN_DISPATCHER_HEALTH_ADDR", "127.0.0.1:9100")
        host, _, port_text = value.partition(":")
        return host or "127.0.0.1", int(port_text or "9100")

    def _publish_tick_metrics(self) -> None:
        self._last_tick_at = time.time()
        DISPATCHER_TICKS.inc()
        DISPATCHER_INFLIGHT.set(len(self.futures))

    def _register_capability_catalog(self) -> None:
        response = self.client.register_capability_catalog(capability_catalog_payload(self.config))
        if not response.ok:
            raise RuntimeError(f"failed to register capability catalog status={response.status_code}: {response.text}")
        LOG.info(
            "registered capability catalog mcp_servers=%s skills=%s",
            len(self.config.capabilities.mcp_servers),
            len(self.config.capabilities.skills),
        )

    def _register_role_catalog(self) -> None:
        response = self.client.register_role_catalog(role_catalog_payload(self.config))
        if not response.ok:
            raise RuntimeError(f"failed to register role catalog status={response.status_code}: {response.text}")
        LOG.info("registered role catalog roles=%s", len(self.config.roles))

    def _reload_from_health_server(self, authorization: str | None) -> dict[str, object]:
        expected = os.environ.get("CAIRN_API_TOKEN", "")
        if expected and authorization != f"Bearer {expected}":
            raise PermissionError("invalid reload token")
        with self._reload_lock:
            next_config = DispatchConfig.load(self.config_path)
            bearer_token_env_keys = tuple(
                mcp.bearer_token_env
                for mcp in next_config.capabilities.mcp_servers
                if mcp.transport == "http" and mcp.bearer_token_env
            )
            next_container_manager = ContainerManager(
                next_config.container,
                bearer_token_env_keys=bearer_token_env_keys,
                proxy_resolver=self._resolve_proxy_env,
            )
            old_container_manager = self.container_manager
            old_executor = self.executor
            old_cleanup_executor = self.cleanup_executor
            self.config = next_config
            self.client.close()
            self.client._base_url = next_config.server.rstrip("/")  # noqa: SLF001 - reloads existing client wiring.
            self.container_manager = next_container_manager
            self.executor = ThreadPoolExecutor(max_workers=next_config.runtime.max_workers)
            self.cleanup_executor = ThreadPoolExecutor(max_workers=max(1, min(8, next_config.runtime.max_workers)))
            self.project_caches.clear_all()
            self._ai_overlay_cache.invalidate()
            self.worker_unhealthy_until.clear()
            self.worker_rejected_until.clear()
            self._settings_checked = False
            self._capability_catalog_registered = False
            self._role_catalog_registered = False
            self._ai_catalog_synced = False
            try:
                old_container_manager.close()
            finally:
                old_executor.shutdown(wait=False, cancel_futures=False)
                old_cleanup_executor.shutdown(wait=False, cancel_futures=False)
        LOG.info("dispatcher config reloaded workers=%s", len(self.config.workers))
        return {"ok": True, "workers": len(self.config.workers)}

    def _dispatch_available(self, summaries: list[ProjectSummary]) -> None:
        if len(self.futures) >= self.config.runtime.max_workers:
            DISPATCHER_OVERFLOW.labels(reason="max_workers").inc()
            self._log_changed(
                "dispatch/global",
                logging.INFO,
                "skip dispatch because max_workers reached running_tasks=%s",
                len(self.futures),
            )
            return
        active = [summary for summary in summaries if summary.status == "active"]
        if not active:
            self._log_changed("dispatch/global", logging.INFO, "skip dispatch because no active projects")
            return

        running_projects = self._ordered_projects(
            [summary for summary in active if summary.id in self.runtime_project_ids]
        )
        idle_projects = self._ordered_projects(
            [summary for summary in active if summary.id not in self.runtime_project_ids]
        )

        dispatched = True
        while dispatched and len(self.futures) < self.config.runtime.max_workers:
            dispatched = False
            for summary in running_projects:
                if self._try_dispatch_project(summary):
                    dispatched = True
                    if len(self.futures) >= self.config.runtime.max_workers:
                        return
            if dispatched:
                continue
            if self._running_project_count(active) >= self.config.runtime.max_running_projects:
                self._log_changed(
                    "dispatch/idle-limit",
                    logging.INFO,
                    "skip idle project dispatch because max_running_projects reached running_projects=%s",
                    self._running_project_count(active),
                )
                return
            for summary in idle_projects:
                if self._running_project_count(active) >= self.config.runtime.max_running_projects:
                    self._log_changed(
                        "dispatch/idle-limit",
                        logging.INFO,
                        "stop idle project dispatch because max_running_projects reached running_projects=%s",
                        self._running_project_count(active),
                    )
                    return
                if self._try_dispatch_project(summary):
                    dispatched = True
                    break

    def _ordered_projects(self, summaries: list[ProjectSummary]) -> list[ProjectSummary]:
        if not summaries:
            return []
        ids = [summary.id for summary in summaries]
        ids.sort()
        offset = self.project_cursor % len(ids)
        ordered_ids = ids[offset:] + ids[:offset]
        by_id = {summary.id: summary for summary in summaries}
        self.project_cursor += 1
        return [by_id[project_id] for project_id in ordered_ids]

    def _resolve_project_proxy(self, project: ProjectDetail) -> None:
        """Refresh ``self._project_proxy_cache`` for one project.

        Called from :meth:`_try_dispatch_project` on every dispatch pass so
        that the cache always reflects the latest ``projects.proxy_id`` and
        proxy definition. A proxy_id of ``None`` (or a missing/errored fetch)
        is cached as ``None``.
        """
        project_id = project.project.id
        proxy_id = project.proxy.id if project.proxy else None
        if not proxy_id:
            self.project_caches.set_proxy(project_id, None)
            self._ai_overlay_cache.invalidate(project_id)
            return
        try:
            self.project_caches.set_proxy(project_id, self.client.get_proxy(proxy_id))
            # Proxy env is part of the AI overlay; invalidate so the
            # next tick rebuilds overlays for this project.
            self._ai_overlay_cache.invalidate(project_id)
            LOG.info("resolved proxy for project=%s proxy_id=%s", project_id, proxy_id)
        except LookupError:
            LOG.warning(
                "project=%s references missing proxy_id=%s; worker will run direct",
                project_id,
                proxy_id,
            )
            self.project_caches.set_proxy(project_id, None)
            self._ai_overlay_cache.invalidate(project_id)
        except requests.RequestException as exc:
            LOG.warning(
                "project=%s proxy lookup failed proxy_id=%s error=%s; worker will run direct",
                project_id,
                proxy_id,
                exc,
            )
            self.project_caches.set_proxy(project_id, None)

    def _resolve_project_ai_selection(self, project: ProjectDetail) -> None:
        """Refresh the per-project AI selection cache.

        Caches ``None`` when the project has not opted into AI profiles.
        Otherwise caches the ordered list of snapshots (primary first, then
        fallback by position). API or parse failures are tolerated and
        cached as ``None`` so dispatch can keep going.
        """
        project_id = project.project.id
        try:
            response = self.client.get_project_ai_profiles(project_id)
        except Exception as exc:  # noqa: BLE001 - tolerate any client glitch
            LOG.warning(
                "project=%s ai profile fetch raised error=%s; missing AI profile selection",
                project_id,
                exc,
            )
            self.project_caches.set_ai_chains(project_id, None)
            return
        if not response.ok or not isinstance(response.data, dict):
            self.project_caches.set_ai_chains(project_id, None)
            return
        data = response.data
        try:
            snapshots = [ProjectAiProfileSnapshot.model_validate(item) for item in data.get("snapshots", [])]
        except Exception as exc:  # noqa: BLE001
            LOG.warning(
                "project=%s ai profile snapshot parse failed error=%s; missing AI profile selection",
                project_id,
                exc,
            )
            self.project_caches.set_ai_chains(project_id, None)
            return
        chains: dict[str, list[ProjectAiProfileSnapshot]] = {}
        for task_type in ("bootstrap", "explore", "reason"):
            task_snaps = [snap for snap in snapshots if snap.task_type == task_type]
            ordered = sorted(
                task_snaps,
                key=lambda snap: (0 if snap.role == "primary" else 1, snap.position),
            )
            if ordered:
                chains[task_type] = ordered
        if not chains:
            self.project_caches.set_ai_chains(project_id, None)
            return
        self.project_caches.set_ai_chains(project_id, chains)
        # Fetch the raw ``sk`` value for every referenced profile. Failures
        # are tolerated and cached as ``None`` so a transient server
        # glitch does not take down dispatch.
        secrets: dict[str, str | None] = {}
        seen_profile_ids: set[str] = set()
        for ordered in chains.values():
            for snap in ordered:
                if snap.profile_id in seen_profile_ids:
                    continue
                seen_profile_ids.add(snap.profile_id)
                try:
                    secrets[snap.profile_id] = self.client.get_ai_profile_secret(snap.profile_id)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning(
                        "project=%s ai profile secret fetch failed profile=%s error=%s",
                        project_id, snap.profile_id, exc,
                    )
                    secrets[snap.profile_id] = None
        self.project_caches.set_ai_secret(project_id, secrets)
        # Secrets changed, so any cached overlay that referenced them
        # is stale.
        self._ai_overlay_cache.invalidate(project_id)
        for task_type, ordered in chains.items():
            LOG.info(
                "project=%s ai selection task_type=%s primary=%s fallback=%s",
                project_id,
                task_type,
                next((snap.profile_id for snap in ordered if snap.role == "primary"), None),
                [snap.profile_id for snap in ordered if snap.role == "fallback"],
            )

    def _project_ai_snapshots(self, project_id: str, task_type: str) -> list[ProjectAiProfileSnapshot]:
        chains = self.project_caches.get_ai_chains(project_id) or {}
        return chains.get(task_type) or []

    def _ai_worker_env_overlay(self, project_id: str, snapshot: ProjectAiProfileSnapshot) -> dict[str, str]:
        """Translate a snapshot into the env-var overlay for the matching worker.

        Delegates to :func:`cairn.dispatcher.scheduler.ai_overlay.compute_ai_overlay`
        so the same code path is unit-testable in isolation. The TTL
        cache here short-circuits the per-tick host env lookup and the
        AI selection cache lookup, which together account for a
        meaningful chunk of the dispatcher's per-tick HTTP traffic
        (3s tick × N projects × chain length).
        """
        cached = self._ai_overlay_cache.get(project_id, snapshot)
        if cached is not None:
            return cached
        secrets = self.project_caches.get_ai_secret(project_id)
        cached_secret = secrets.get(snapshot.profile_id) or None
        proxy_cfg = self.project_caches.get_proxy(project_id)
        overlay = compute_ai_overlay(
            snapshot,
            cached_secret=cached_secret,
            proxy_config=proxy_cfg,
        )
        self._ai_overlay_cache.put(project_id, snapshot, overlay)
        return overlay

    def _resolve_proxy_env(self, project_id: str) -> dict[str, str] | None:
        """Resolver passed to :class:`ContainerManager`.

        Returns the proxy env vars to merge into the worker's ``environment=``
        kwarg. ``None`` means "no proxy" (the worker runs direct). The
        startup-healthcheck container is special-cased to ``None`` so the
        probe never tries to dial a proxy that may not be reachable from
        inside the dispatcher's network namespace.
        """
        if project_id == ContainerManager._STARTUP_PROJECT_ID:
            return None
        cfg = self.project_caches.get_proxy(project_id)
        if cfg is None:
            return None
        return _proxy_config_to_env(cfg)

    def _try_dispatch_project(self, summary: ProjectSummary) -> bool:
        skip_scope = f"project:{summary.id}:skip"
        container_name = self.container_manager.container_name(summary.id)
        if container_name in self._cleanup_pending:
            self._log_changed(
                f"{skip_scope}:cleanup_pending",
                logging.DEBUG,
                "skip project=%s because container cleanup is still pending container=%s",
                summary.id,
                container_name,
            )
            return False
        if self._project_running_task_count(summary.id) >= self.config.runtime.max_project_workers:
            self._log_changed(
                f"{skip_scope}:max_project_workers",
                logging.INFO,
                "skip project=%s because max_project_workers reached running_tasks=%s",
                summary.id,
                self._project_running_task_summary(summary.id),
            )
            return False

        project = self.client.get_project(summary.id)
        # Populate the per-project AI selection cache alongside the proxy
        # cache. The first dispatch pass queries the server; later passes
        # reuse the cache so dispatch stays cheap.
        self._resolve_project_ai_selection(project)
        # Populate the per-project proxy cache *before* any skip checks so
        # that even short-circuit returns (status != active, etc.) keep the
        # cache consistent. Resolver failures are tolerated: a project
        # whose proxy_id points to a deleted proxy simply runs direct.
        self._resolve_project_proxy(project)
        if project.project.status != "active":
            self._log_changed(
                f"{skip_scope}:status",
                logging.INFO,
                "skip project=%s because status=%s",
                summary.id,
                project.project.status,
            )
            return False
        replay_action = self._advance_replay_project(project.project.id)
        if replay_action is not None:
            return replay_action
        if self._is_initial_project(project):
            if project.project.reason is not None:
                return False
            return self._dispatch_initial_project(project)
        running_intent_ids = self._project_running_explore_intents(summary.id)
        unclaimed_intents = [
            intent
            for intent in project.intents
            if intent.to is None
            and intent.worker is None
            and intent.id not in running_intent_ids
            and not self._is_bootstrap_intent(intent)
        ]
        if running_intent_ids and not unclaimed_intents:
            self._log_changed(
                f"{skip_scope}:explore_running",
                logging.DEBUG,
                "skip explore project=%s because all unclaimed intents are already running locally intents=%s",
                summary.id,
                sorted(running_intent_ids),
            )
        if unclaimed_intents:
            newest = max(unclaimed_intents, key=lambda i: i.created_at)
            export_yaml = self.client.export_project(summary.id)
            return self._dispatch_explore(project, export_yaml, newest)
        if project.project.reason is not None:
            self._log_changed(
                f"{skip_scope}:reason_claimed",
                logging.DEBUG,
                "skip reason project=%s because reason is already claimed by %s",
                summary.id,
                project.project.reason.worker,
            )
            return False
        reason_trigger = self._reason_trigger(project)
        if reason_trigger is None:
            self._log_changed(
                f"{skip_scope}:graph_unchanged",
                logging.DEBUG,
                "skip reason project=%s because reason state unchanged facts=%s hints=%s open_intents=%s intents=%s",
                summary.id,
                len(project.facts),
                len(project.hints),
                self._project_open_intent_count(project),
                len(project.intents),
            )
            return False
        reason_trigger_hash = self._reason_trigger_hash(reason_trigger)
        reason_blocker = self._reason_dispatch_blocker(project, reason_trigger_hash)
        if reason_blocker is not None:
            self._log_changed(
                f"{skip_scope}:reason_state",
                logging.INFO,
                "skip reason project=%s trigger=%s reason=%s",
                summary.id,
                reason_trigger,
                reason_blocker,
            )
            return False
        export_yaml = self.client.export_project(summary.id)
        return self._dispatch_reason(project, export_yaml, reason_trigger, reason_trigger_hash)

    def _advance_replay_project(self, project_id: str) -> bool | None:
        response = self.client.advance_replay_run(project_id)
        if response.status_code == 404:
            return None
        if not response.ok:
            self._log_changed(
                f"project:{project_id}:replay_advance_error",
                logging.WARNING,
                "replay advance failed project=%s status=%s body=%s",
                project_id,
                response.status_code,
                response.text,
            )
            return False
        data = response.data
        if not isinstance(data, dict) or not data.get("is_replay"):
            return None
        action = str(data.get("action") or "")
        if action == "created_intent":
            self._clear_project_log_state(project_id)
            LOG.info("advanced replay project=%s created_intent=%s", project_id, data.get("intent_id"))
            return True
        if action == "completed":
            self._clear_project_log_state(project_id)
            LOG.info("advanced replay project=%s completed", project_id)
            return True
        if action == "blocked":
            self._log_changed(
                f"project:{project_id}:replay_blocked",
                logging.WARNING,
                "replay project blocked project=%s detail=%s",
                project_id,
                data.get("detail") or "",
            )
            return False
        if action == "waiting":
            return None
        self._log_changed(
            f"project:{project_id}:replay_waiting",
            logging.DEBUG,
            "replay project waiting project=%s action=%s intent=%s",
            project_id,
            action,
            data.get("intent_id"),
        )
        return False

    def _dispatch_initial_project(self, project: ProjectDetail) -> bool:
        intent = self._get_bootstrap_intent(project)
        if intent is None:
            intent = self._create_bootstrap_intent(project.project.id)
            if intent is None:
                return False
        if self._project_has_running_bootstrap(project.project.id):
            self._log_changed(
                f"project:{project.project.id}:skip:bootstrap_running",
                logging.DEBUG,
                "skip bootstrap project=%s because bootstrap task is already running locally",
                project.project.id,
            )
            return False
        if intent.worker is not None:
            self._log_changed(
                f"project:{project.project.id}:skip:bootstrap_claimed",
                logging.DEBUG,
                "skip bootstrap project=%s because bootstrap intent=%s is already claimed by %s",
                project.project.id,
                intent.id,
                intent.worker,
            )
            return False
        return self._dispatch_bootstrap(project, intent)

    def _dispatch_reason(self, project: ProjectDetail, export_yaml: str, trigger: str, trigger_hash: str) -> bool:
        selection = self._select_worker(project.project.id, "reason")
        worker = selection.worker
        if worker is None:
            self._log_changed(
                f"project:{project.project.id}:worker:reason",
                logging.INFO,
                "no worker available for reason project=%s blocked_busy=%s blocked_unhealthy=%s blocked_rejected=%s",
                project.project.id,
                selection.blocked_busy,
                selection.blocked_unhealthy,
                selection.blocked_rejected,
            )
            return False
        self._clear_log_state(f"project:{project.project.id}:worker:reason")
        fact_count = len(project.facts)
        hint_count = len(project.hints)
        open_intent_count = self._project_open_intent_count(project)
        run_id = uuid.uuid4().hex
        claim = self.client.claim_reason(
            project.project.id,
            worker.name,
            trigger,
            run_id=run_id,
            trigger_hash=trigger_hash,
            fact_count=fact_count,
            hint_count=hint_count,
            open_intent_count=open_intent_count,
        )
        if claim.status_code in (403, 409):
            level = logging.INFO if claim.status_code == 403 else logging.WARNING
            LOG.log(
                level,
                "reason claim failed project=%s worker=%s status=%s",
                project.project.id,
                worker.name,
                claim.status_code,
            )
            return False
        if not claim.ok:
            LOG.warning(
                "reason claim failed project=%s worker=%s status=%s",
                project.project.id,
                worker.name,
                claim.status_code,
            )
            return False
        try:
            future = self.executor.submit(
                run_reason_task,
                self.config,
                self.client,
                self.container_manager,
                project,
                export_yaml,
                worker,
                run_id,
                trigger,
                trigger_hash,
                fact_count,
                hint_count,
                open_intent_count,
                cancellation := TaskCancellation(),
            )
        except Exception:
            LOG.exception("failed to submit reason task project=%s worker=%s", project.project.id, worker.name)
            self._best_effort_release_reason(project.project.id, worker.name)
            return False
        self.futures[future] = RunningTask(
            project.project.id,
            "reason",
            worker.name,
            cancellation,
            intent_id=None,
            fact_count=fact_count,
            hint_count=hint_count,
            open_intent_count=open_intent_count,
            reason_trigger=trigger,
            reason_trigger_hash=trigger_hash,
        )
        self.runtime_project_ids.add(project.project.id)
        self._clear_project_log_state(project.project.id)
        LOG.info("dispatched reason project=%s worker=%s trigger=%s", project.project.id, worker.name, trigger)
        return True

    def _dispatch_bootstrap(self, project: ProjectDetail, intent: Intent) -> bool:
        selection = self._select_worker(project.project.id, "bootstrap")
        worker = selection.worker
        if worker is None:
            self._log_changed(
                f"project:{project.project.id}:worker:bootstrap",
                logging.INFO,
                "no worker available for bootstrap project=%s intent=%s blocked_busy=%s blocked_unhealthy=%s blocked_rejected=%s",
                project.project.id,
                intent.id,
                selection.blocked_busy,
                selection.blocked_unhealthy,
                selection.blocked_rejected,
            )
            return False
        self._clear_log_state(f"project:{project.project.id}:worker:bootstrap")
        claim = self.client.heartbeat(project.project.id, intent.id, worker.name)
        if claim.status_code in (403, 409):
            level = logging.INFO if claim.status_code == 403 else logging.WARNING
            LOG.log(
                level,
                "bootstrap claim failed project=%s intent=%s worker=%s status=%s",
                project.project.id,
                intent.id,
                worker.name,
                claim.status_code,
            )
            return False
        if not claim.ok:
            LOG.warning(
                "bootstrap claim failed project=%s intent=%s worker=%s status=%s",
                project.project.id,
                intent.id,
                worker.name,
                claim.status_code,
            )
            return False
        try:
            future = self.executor.submit(
                run_bootstrap_task,
                self.config,
                self.client,
                self.container_manager,
                project,
                intent,
                worker,
                cancellation := TaskCancellation(),
            )
        except Exception:
            LOG.exception("failed to submit bootstrap task project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
            self._best_effort_release(project.project.id, intent.id, worker.name)
            return False
        self.futures[future] = RunningTask(project.project.id, "bootstrap", worker.name, cancellation, intent_id=intent.id)
        self.runtime_project_ids.add(project.project.id)
        self._clear_project_log_state(project.project.id)
        LOG.info("dispatched bootstrap project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        return True

    def _dispatch_explore(self, project: ProjectDetail, export_yaml: str, intent: Intent) -> bool:
        selection = self._select_worker(project.project.id, "explore")
        worker = selection.worker
        if worker is None:
            self._log_changed(
                f"project:{project.project.id}:worker:explore",
                logging.INFO,
                "no worker available for explore project=%s intent=%s blocked_busy=%s blocked_unhealthy=%s blocked_rejected=%s",
                project.project.id,
                intent.id,
                selection.blocked_busy,
                selection.blocked_unhealthy,
                selection.blocked_rejected,
            )
            return False
        self._clear_log_state(f"project:{project.project.id}:worker:explore")
        claim = self.client.heartbeat(project.project.id, intent.id, worker.name)
        if claim.status_code in (403, 409):
            level = logging.INFO if claim.status_code == 403 else logging.WARNING
            LOG.log(
                level,
                "explore claim failed project=%s intent=%s worker=%s status=%s",
                project.project.id,
                intent.id,
                worker.name,
                claim.status_code,
            )
            return False
        if not claim.ok:
            LOG.warning(
                "explore claim failed project=%s intent=%s worker=%s status=%s",
                project.project.id,
                intent.id,
                worker.name,
                claim.status_code,
            )
            return False
        try:
            future = self.executor.submit(
                run_explore_task,
                self.config,
                self.client,
                self.container_manager,
                project,
                export_yaml,
                intent,
                worker,
                cancellation := TaskCancellation(),
            )
        except Exception:
            LOG.exception("failed to submit explore task project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
            self._best_effort_release(project.project.id, intent.id, worker.name)
            return False
        self.futures[future] = RunningTask(project.project.id, "explore", worker.name, cancellation, intent_id=intent.id)
        self.runtime_project_ids.add(project.project.id)
        self._clear_project_log_state(project.project.id)
        LOG.info("dispatched explore project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        return True

    def _select_worker(self, project_id: str, task_type: str) -> WorkerSelection:
        snapshots = self._project_ai_snapshots(project_id, task_type)
        if snapshots:
            return self._select_worker_for_ai_chain(project_id, task_type, snapshots)
        return self._select_worker_default(project_id, task_type)

    def _select_worker_default(self, project_id: str, task_type: str) -> WorkerSelection:
        return select_worker_default(
            project_id=project_id,
            task_type=task_type,
            workers=self.config.workers,
            running_counts=self._worker_counts(),
            worker_unhealthy_until=self.worker_unhealthy_until,
            worker_rejected_until=self.worker_rejected_until,
        )

    def _select_worker_for_ai_chain(
        self,
        project_id: str,
        task_type: str,
        snapshots: list[ProjectAiProfileSnapshot],
    ) -> WorkerSelection:
        """Select a worker constrained by the project AI profile chain.

        Walks the chain in order (primary, fallback[0], fallback[1], ...).
        For each snapshot:
          * resolve the env overlay; if the referenced api_key_env is
            missing locally, mark the snapshot unavailable and continue;
          * filter workers by snapshot.snapshot_worker_type and the
            worker's required env keys, then apply the existing
            busy/unhealthy/rejected filters via the shared helper.
        The first snapshot that yields an available worker wins; the
        returned worker is a *copy* of the WorkerConfig with the env
        overlay merged in so the container sees the chosen AI config.
        """
        now = time.time()
        running_counts = self._worker_counts()
        last_unavailable_reasons: list[str] = []
        for snap in snapshots:
            # Run the per-task health probe (api_key_env present, base_url
            # reachable, worker_type declared) before consulting workers.
            # We do not mutate the catalog here — only this dispatch pass
            # sees the failure. The catalog's ``available`` flag is updated
            # by the periodic health-report pass at startup.
            try:
                health = probe_snapshot(snap, config=self.config)
            except Exception as exc:  # noqa: BLE001
                LOG.warning(
                    "ai profile probe raised project=%s profile=%s error=%s",
                    project_id, snap.profile_id, exc,
                )
                continue
            if not health.ok:
                bad = [item for item in health.checks if not item.ok]
                reason = (
                    f"{snap.profile_id}({snap.snapshot_worker_type}) "
                    f"health checks failed: " + "; ".join(
                        f"{item.name}={item.message or 'fail'}" for item in bad
                    )
                )
                last_unavailable_reasons.append(reason)
                LOG.info(
                    "ai profile unavailable project=%s profile=%s reason=%s",
                    project_id, snap.profile_id, reason,
                )
                continue
            overlay = self._ai_worker_env_overlay(project_id, snap)
            if not overlay and snap.snapshot_api_key_env:
                reason = (
                    f"{snap.profile_id}({snap.snapshot_worker_type}) env "
                    f"{snap.snapshot_api_key_env} not set on dispatcher"
                )
                last_unavailable_reasons.append(reason)
                LOG.info(
                    "ai profile unavailable project=%s profile=%s reason=%s",
                    project_id, snap.profile_id, reason,
                )
                continue
            if not overlay:
                # No api_key_env at all: still allow the snapshot, but log it.
                LOG.info(
                    "ai profile has no api_key_env project=%s profile=%s",
                    project_id, snap.profile_id,
                )
            matching_workers = [
                worker for worker in self.config.workers
                if worker.type == snap.snapshot_worker_type
            ]
            if not matching_workers:
                reason = (
                    f"{snap.profile_id}({snap.snapshot_worker_type}) no matching worker in dispatch.yaml"
                )
                last_unavailable_reasons.append(reason)
                LOG.info(
                    "ai profile unavailable project=%s profile=%s reason=%s",
                    project_id, snap.profile_id, reason,
                )
                continue
            blocked_busy: list[str] = []
            blocked_unhealthy: list[str] = []
            blocked_rejected: list[str] = []
            blocked_task_type: list[str] = []
            candidates: list[WorkerConfig] = []
            for worker in matching_workers:
                if task_type not in worker.task_types:
                    blocked_task_type.append(worker.name)
                    continue
                running = running_counts.get(worker.name, 0)
                if running >= worker.max_running:
                    blocked_busy.append(f"{worker.name}({running}/{worker.max_running})")
                    continue
                unhealthy_until = self.worker_unhealthy_until.get(worker.name, 0)
                if unhealthy_until > now:
                    blocked_unhealthy.append(f"{worker.name}({unhealthy_until - now:.1f}s)")
                    continue
                rejected_until = self.worker_rejected_until.get((project_id, task_type, worker.name), 0)
                if rejected_until > now:
                    blocked_rejected.append(f"{worker.name}({rejected_until - now:.1f}s)")
                    continue
                candidates.append(worker)
            if not candidates:
                reason = (
                    f"{snap.profile_id}({snap.snapshot_worker_type}) no healthy candidate "
                    f"task_type={task_type} busy={blocked_busy} unhealthy={blocked_unhealthy} "
                    f"rejected={blocked_rejected} task_type_blocked={blocked_task_type}"
                )
                last_unavailable_reasons.append(reason)
                LOG.info(
                    "ai profile fallthrough project=%s profile=%s reason=%s",
                    project_id, snap.profile_id, reason,
                )
                continue
            ordered = choose_worker(candidates, running_counts)
            base = ordered[0]
            chosen = base.model_copy(update={"env": {**base.env, **overlay}})
            LOG.info(
                "ai profile selected project=%s profile=%s worker=%s task_type=%s",
                project_id, snap.profile_id, chosen.name, task_type,
            )
            return WorkerSelection(
                worker=chosen,
                blocked_busy=blocked_busy,
                blocked_unhealthy=blocked_unhealthy,
                blocked_rejected=blocked_rejected,
                blocked_task_type=blocked_task_type,
            )
        LOG.warning(
            "ai selection exhausted project=%s task_type=%s reasons=%s",
            project_id, task_type, last_unavailable_reasons,
        )
        return WorkerSelection(
            worker=None,
            blocked_busy=[],
            blocked_unhealthy=[],
            blocked_rejected=[],
            blocked_task_type=[],
        )

    def _worker_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.futures.values():
            counts[task.worker_name] = counts.get(task.worker_name, 0) + 1
        return counts

    def _project_running_task_count(self, project_id: str) -> int:
        return sum(1 for task in self.futures.values() if task.project_id == project_id)

    def _project_running_task_summary(self, project_id: str) -> list[str]:
        summary: list[str] = []
        for task in self.futures.values():
            if task.project_id != project_id:
                continue
            if task.intent_id is None:
                summary.append(f"{task.task_type}:{task.worker_name}")
            else:
                summary.append(f"{task.task_type}:{task.worker_name}:{task.intent_id}")
        summary.sort()
        return summary

    def _project_has_running_bootstrap(self, project_id: str) -> bool:
        return any(task.project_id == project_id and task.task_type == "bootstrap" for task in self.futures.values())

    def _project_running_explore_intents(self, project_id: str) -> set[str]:
        return {
            task.intent_id
            for task in self.futures.values()
            if task.project_id == project_id and task.task_type == "explore" and task.intent_id is not None
        }

    def _running_project_count(self, summaries: list[ProjectSummary]) -> int:
        active_ids = {summary.id for summary in summaries if summary.status == "active"}
        return len(self.runtime_project_ids & active_ids)

    def _project_open_intent_count(self, project: ProjectDetail) -> int:
        return sum(1 for intent in project.intents if intent.to is None)

    def _is_bootstrap_intent(self, intent: Intent) -> bool:
        return (
            intent.description == BOOTSTRAP_INTENT_DESCRIPTION
            and intent.creator == BOOTSTRAP_INTENT_CREATOR
            and intent.from_ == ["origin"]
            and intent.to is None
        )

    def _get_bootstrap_intent(self, project: ProjectDetail) -> Intent | None:
        intents = [intent for intent in project.intents if self._is_bootstrap_intent(intent)]
        if not intents:
            return None
        if len(intents) > 1:
            LOG.warning("project has multiple bootstrap intents project=%s intents=%s", project.project.id, [intent.id for intent in intents])
        intents.sort(key=lambda intent: (intent.worker is not None, intent.created_at, intent.id))
        return intents[0]

    def _is_initial_project(self, project: ProjectDetail) -> bool:
        fact_ids = {fact.id for fact in project.facts}
        if fact_ids != {"origin", "goal"} or len(project.facts) != 2:
            return False
        if not project.intents:
            return True
        return all(self._is_bootstrap_intent(intent) for intent in project.intents)

    def _create_bootstrap_intent(self, project_id: str) -> Intent | None:
        response = self.client.create_intent(
            project_id,
            ["origin"],
            BOOTSTRAP_INTENT_DESCRIPTION,
            BOOTSTRAP_INTENT_CREATOR,
        )
        if response.status_code == 403:
            LOG.info("project became inactive before bootstrap intent create project=%s", project_id)
            return None
        if not response.ok:
            LOG.warning(
                "bootstrap intent write failed project=%s status=%s body=%s",
                project_id,
                response.status_code,
                response.text,
            )
            return None
        if not isinstance(response.data, dict):
            LOG.warning("bootstrap intent create returned empty body project=%s", project_id)
            return None
        intent = Intent.model_validate(response.data)
        LOG.info("created bootstrap intent project=%s intent=%s", project_id, intent.id)
        return intent

    def _reason_trigger(self, project: ProjectDetail) -> str | None:
        open_intent_count = self._project_open_intent_count(project)
        checkpoint = self.reason_checkpoints.get(project.project.id)
        if checkpoint is None:
            return "initial"
        changes: list[str] = []
        if len(project.facts) > checkpoint.fact_count:
            changes.append(f"facts:{checkpoint.fact_count}->{len(project.facts)}")
        if len(project.hints) > checkpoint.hint_count:
            changes.append(f"hints:{checkpoint.hint_count}->{len(project.hints)}")
        if checkpoint.open_intent_count > 0 and open_intent_count == 0:
            changes.append(f"open_intents:{checkpoint.open_intent_count}->0")
        if not changes:
            return None
        return ",".join(changes)

    @staticmethod
    def _reason_trigger_hash(trigger: str) -> str:
        return sha256(trigger.encode("utf-8")).hexdigest()

    def _reason_dispatch_blocker(self, project: ProjectDetail, trigger_hash: str) -> str | None:
        try:
            response = self.client.get_reason_state(project.project.id)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("reason state fetch raised project=%s error=%s", project.project.id, exc)
            return None
        if not response.ok:
            LOG.warning(
                "reason state fetch failed project=%s status=%s",
                project.project.id,
                response.status_code,
            )
            return None
        state = response.data
        if state is None:
            return None
        if (
            state.trigger_hash != trigger_hash
            or state.fact_count != len(project.facts)
            or state.hint_count != len(project.hints)
            or state.open_intent_count != self._project_open_intent_count(project)
        ):
            return None
        if state.outcome in REASON_CONSUMED_OUTCOMES:
            return f"already consumed outcome={state.outcome}"
        if state.next_retry_at and state.next_retry_at > time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()):
            return f"backoff until {state.next_retry_at}"
        return None

    def _reap_futures(self) -> None:
        done = [future for future in self.futures if future.done()]
        for future in done:
            task = self.futures.pop(future)
            try:
                outcome = future.result()
                if outcome == "cancelled":
                    LOG.info(
                        "task cancelled project=%s task=%s worker=%s",
                        task.project_id,
                        task.task_type,
                        task.worker_name,
                    )
                elif outcome != "success":
                    LOG.warning(
                        "task finished project=%s task=%s worker=%s outcome=%s",
                        task.project_id,
                        task.task_type,
                        task.worker_name,
                        outcome,
                    )
                self._clear_project_log_state(task.project_id)
                if outcome == "unhealthy":
                    retry_after_seconds = UNHEALTHY_RETRY_AFTER_SECONDS
                    self.worker_unhealthy_until[task.worker_name] = time.time() + retry_after_seconds
                    WORKER_UNHEALTHY_SINCE.labels(worker=task.worker_name).set(time.time())
                    LOG.info(
                        "worker marked unhealthy worker=%s retry_after=%.0fs",
                        task.worker_name,
                        retry_after_seconds,
                    )
                else:
                    self.worker_unhealthy_until.pop(task.worker_name, None)
                    WORKER_UNHEALTHY_SINCE.labels(worker=task.worker_name).set(0)
                rejection_key = (task.project_id, task.task_type, task.worker_name)
                if outcome == "rejected":
                    retry_after_seconds = REJECTED_RETRY_AFTER_SECONDS
                    self.worker_rejected_until[rejection_key] = time.time() + retry_after_seconds
                    LOG.info(
                        "worker marked rejected project=%s task=%s worker=%s retry_after=%.0fs",
                        task.project_id,
                        task.task_type,
                        task.worker_name,
                        retry_after_seconds,
                    )
                else:
                    self.worker_rejected_until.pop(rejection_key, None)
                if outcome == "success" and task.task_type == "reason":
                    assert task.fact_count is not None
                    assert task.hint_count is not None
                    assert task.open_intent_count is not None
                    self.reason_checkpoints[task.project_id] = ReasonCheckpoint(
                        fact_count=task.fact_count,
                        hint_count=task.hint_count,
                        open_intent_count=task.open_intent_count,
                    )
                    LOG.debug(
                        "reason checkpoint updated project=%s facts=%s hints=%s open_intents=%s",
                        task.project_id,
                        task.fact_count,
                        task.hint_count,
                        task.open_intent_count,
                    )
            except Exception:
                LOG.exception("task crashed project=%s task=%s worker=%s", task.project_id, task.task_type, task.worker_name)

    def _cleanup_completed_containers(self, summaries: list[ProjectSummary]) -> None:
        for summary in summaries:
            if summary.status != "completed":
                continue
            if self._inactive_cleanup_done.get(summary.id) == summary.status:
                continue
            container_name = self.container_manager.container_name(summary.id)
            if container_name in self._cleanup_pending:
                continue
            if not self.container_manager.needs_completed_cleanup(summary.id):
                self._inactive_cleanup_done[summary.id] = summary.status
                continue
            future = self.cleanup_executor.submit(self.container_manager.cleanup_completed, summary.id)
            self.cleanup_futures[future] = (container_name, summary.id, summary.status)
            self._cleanup_pending.add(container_name)

    def _cleanup_stopped_containers(self, summaries: list[ProjectSummary]) -> None:
        for summary in summaries:
            if summary.status != "stopped":
                continue
            if self._inactive_cleanup_done.get(summary.id) == summary.status:
                continue
            container_name = self.container_manager.container_name(summary.id)
            if container_name in self._cleanup_pending:
                continue
            if not self.container_manager.needs_stopped_cleanup(summary.id):
                self._inactive_cleanup_done[summary.id] = summary.status
                continue
            future = self.cleanup_executor.submit(self.container_manager.cleanup_stopped, summary.id)
            self.cleanup_futures[future] = (container_name, summary.id, summary.status)
            self._cleanup_pending.add(container_name)

    def _cleanup_orphan_containers(self, summaries: list[ProjectSummary]) -> None:
        expected_container_names = {self.container_manager.container_name(summary.id) for summary in summaries}
        for container_name in self.container_manager.managed_container_names():
            if container_name in expected_container_names:
                continue
            if container_name in self._cleanup_pending:
                continue
            if not self.container_manager.needs_orphan_cleanup(container_name):
                continue
            future = self.cleanup_executor.submit(self.container_manager.cleanup_orphan, container_name)
            self.cleanup_futures[future] = (container_name, None, None)
            self._cleanup_pending.add(container_name)

    def _queue_container_cleanups(self, summaries: list[ProjectSummary]) -> None:
        self._cleanup_completed_containers(summaries)
        self._cleanup_stopped_containers(summaries)
        self._cleanup_orphan_containers(summaries)

    def _reap_cleanup_futures(self) -> None:
        done = [future for future in self.cleanup_futures if future.done()]
        for future in done:
            name, project_id, target_status = self.cleanup_futures.pop(future)
            self._cleanup_pending.discard(name)
            try:
                success = future.result()
                if success and project_id is not None and target_status in ("completed", "stopped"):
                    self._inactive_cleanup_done[project_id] = target_status
                elif project_id is not None:
                    self._inactive_cleanup_done.pop(project_id, None)
            except Exception:
                if project_id is not None:
                    self._inactive_cleanup_done.pop(project_id, None)
                LOG.exception("container cleanup failed container=%s", name)

    def _refresh_runtime_projects(self, summaries: list[ProjectSummary]) -> None:
        active_ids = {summary.id for summary in summaries if summary.status == "active"}
        self.runtime_project_ids.intersection_update(active_ids)
        inactive_status_by_id = {summary.id: summary.status for summary in summaries if summary.status != "active"}
        for project_id, status in list(self._inactive_cleanup_done.items()):
            current_status = inactive_status_by_id.get(project_id)
            if current_status != status:
                self._inactive_cleanup_done.pop(project_id, None)

    def _cancel_inactive_tasks(self, summaries: list[ProjectSummary]) -> None:
        status_by_project = {summary.id: summary.status for summary in summaries}
        for task in self.futures.values():
            status = status_by_project.get(task.project_id, "deleted")
            if status != "active" and task.cancellation.cancel(status):
                LOG.info(
                    "cancelling running task for inactive project project=%s task=%s worker=%s status=%s",
                    task.project_id,
                    task.task_type,
                    task.worker_name,
                    status,
                )

    def _initialize_reason_checkpoints(self, summaries: list[ProjectSummary]) -> None:
        for summary in summaries:
            if summary.status != "active":
                continue
            if summary.id in self.reason_checkpoints:
                continue
            open_intent_count = summary.working_intent_count + summary.unclaimed_intent_count
            if open_intent_count == 0:
                continue
            self.reason_checkpoints[summary.id] = ReasonCheckpoint(
                fact_count=summary.fact_count,
                hint_count=summary.hint_count,
                open_intent_count=open_intent_count,
            )
            LOG.debug(
                "reason checkpoint initialized project=%s facts=%s hints=%s open_intents=%s",
                summary.id,
                summary.fact_count,
                summary.hint_count,
                open_intent_count,
            )

    def _best_effort_release(self, project_id: str, intent_id: str, worker_name: str) -> None:
        response = self.client.release(project_id, intent_id, worker_name)
        if not response.ok and response.status_code not in (403, 409):
            LOG.warning("release failed project=%s intent=%s worker=%s status=%s", project_id, intent_id, worker_name, response.status_code)

    def _best_effort_release_reason(self, project_id: str, worker_name: str) -> None:
        response = self.client.release_reason(project_id, worker_name)
        if not response.ok and response.status_code not in (403, 409):
            LOG.warning("reason release failed project=%s worker=%s status=%s", project_id, worker_name, response.status_code)

    def _log_changed(self, scope: str, level: int, message: str, *args: object) -> None:
        state = (level, message, args)
        if self._log_state.get(scope) == state:
            return
        self._log_state[scope] = state
        LOG.log(level, message, *args)

    def _clear_log_state(self, scope: str) -> None:
        self._log_state.pop(scope, None)

    def _clear_project_log_state(self, project_id: str) -> None:
        prefix = f"project:{project_id}:"
        for scope in list(self._log_state):
            if scope.startswith(prefix):
                self._log_state.pop(scope, None)

    def _sync_ai_catalog_from_dispatch_yaml(self) -> None:
        """Idempotently mirror ``dispatch.yaml`` workers into ``ai_profiles``.

        * Reads the current server-side catalog.
        * If empty, builds a seed payload from the dispatcher's
          ``self.config.workers`` (skipping ``pi`` and ``mock``) and
          POSTs it to ``/ai-profiles/sync``.
        * Otherwise (catalog is non-empty) skips the seed; user-defined
          profiles are preserved across dispatcher restarts.
        * After the seed, runs the local health probe and POSTs results
          to ``/ai-profiles/health-report`` so the server's
          ``available`` flag reflects dispatcher-side reality.
        """
        try:
            response = self.client.list_ai_profiles()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ai catalog sync: list_ai_profiles failed error=%s", exc)
            return
        if not response.ok or not isinstance(response.data, list):
            LOG.info(
                "ai catalog sync: list_ai_profiles unavailable status=%s; skipping",
                response.status_code,
            )
            return
        profiles = response.data if isinstance(response.data, list) else []
        payload = {"workers": self._build_ai_sync_payload()}
        if payload["workers"]:
            try:
                sync = self.client.sync_ai_profiles(payload)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("ai catalog sync: sync_ai_profiles failed error=%s", exc)
            else:
                if not sync.ok:
                    LOG.warning(
                        "ai catalog sync: server returned status=%s body=%s",
                        sync.status_code, sync.text[:200],
                    )
                else:
                    LOG.info(
                        "ai catalog synced from dispatch.yaml workers=%s",
                        [w["name"] for w in payload["workers"]],
                    )
                    profiles = sync.data if isinstance(sync.data, list) else []
        else:
            LOG.info("ai catalog sync: no supported workers in dispatch.yaml; using existing profiles")
        # Run the local probe and report results.
        reports = []
        for prof in profiles:
            if not isinstance(prof, dict):
                continue
            profile_id = prof.get("id")
            api_key_env = prof.get("api_key_env")
            base_url = prof.get("base_url")
            worker_type = prof.get("worker_type")
            timeout = float(prof.get("healthcheck_timeout") or 1.0)
            from cairn.dispatcher.ai_health import _check_auth_env, _check_base_url, _check_worker_type
            auth_item = _check_auth_env(api_key_env or "")
            url_item = _check_base_url(base_url or "", timeout)
            type_item = _check_worker_type(worker_type or "", self.config.workers)
            ok = all(item.ok for item in (auth_item, url_item, type_item))
            message_bits = [
                item.message for item in (auth_item, url_item, type_item) if not item.ok
            ]
            message = "; ".join(message_bits) if message_bits else "ok"
            reports.append({
                "profile_id": profile_id,
                "ok": ok,
                "message": message,
            })
        if not reports:
            return
        try:
            self.client.post_ai_health_report({"reports": reports})
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ai catalog sync: health_report failed error=%s", exc)

    def _process_ai_profile_check_requests(self) -> None:
        try:
            claimed = self.client.claim_ai_profile_check_request()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ai profile check: claim failed error=%s", exc)
            return
        if not claimed.ok or not isinstance(claimed.data, dict) or not claimed.data:
            return
        request_id = str(claimed.data.get("id") or "")
        profile_id = str(claimed.data.get("profile_id") or "")
        if not request_id or not profile_id:
            return
        try:
            response = self.client.list_ai_profiles()
            if not response.ok or not isinstance(response.data, list):
                self.client.complete_ai_profile_check_request(
                    request_id, ok=False, message="unable to load ai profile catalog",
                )
                return
            raw = next(
                (item for item in response.data if isinstance(item, dict) and item.get("id") == profile_id),
                None,
            )
            if raw is None:
                self.client.complete_ai_profile_check_request(
                    request_id, ok=False, message=f"ai profile not found: {profile_id}",
                )
                return
            profile = AiProfile.model_validate(raw)
            try:
                cached_secret = self.client.get_ai_profile_secret(profile.id)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("ai profile check: secret lookup failed profile_id=%s error=%s", profile.id, exc)
                cached_secret = None
            health = run_profile_worker_healthcheck(
                profile,
                config=self.config,
                container_manager=self.container_manager,
                cached_secret=cached_secret,
                timeout_seconds=self.config.runtime.healthcheck_timeout,
            )
            message = health.message or ("ok" if health.ok else "worker healthcheck failed")
            self.client.post_ai_health_report({
                "reports": [{
                    "profile_id": profile.id,
                    "ok": health.ok,
                    "message": message[:1000],
                }],
            })
            self.client.complete_ai_profile_check_request(
                request_id, ok=health.ok, message=message[:1000],
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ai profile check failed profile_id=%s error=%s", profile_id, exc)
            try:
                self.client.complete_ai_profile_check_request(
                    request_id, ok=False, message=str(exc)[:1000],
                )
            except Exception:  # noqa: BLE001
                LOG.exception("ai profile check complete failed request_id=%s", request_id)

    def _build_ai_sync_payload(self) -> list[dict[str, object]]:
        """Translate ``dispatch.yaml`` workers into the sync payload.

        Only ``codex`` and ``claudecode`` are sent; ``pi`` and ``mock``
        workers are skipped (no first-class AI profile support yet).
        """
        from cairn.dispatcher.config import WORKER_ENV_KEYS
        supported = {"codex", "claudecode"}
        result: list[dict[str, object]] = []
        for worker in self.config.workers:
            if worker.type not in supported:
                continue
            env = worker.env
            # The dispatcher must declare at least the model env key for
            # sync to make sense; without it the profile would be empty.
            model_key = next((k for k in WORKER_ENV_KEYS[worker.type] if k.endswith("_MODEL")), None)
            base_url_key = next((k for k in WORKER_ENV_KEYS[worker.type] if k.endswith("_BASE_URL")), None)
            auth_token_key = next(
                (k for k in WORKER_ENV_KEYS[worker.type] if k.endswith("_API_KEY") or k.endswith("_AUTH_TOKEN")),
                None,
            )
            if model_key is None or auth_token_key is None:
                continue
            default_model = env.get(model_key, "").strip()
            auth_value = env.get(auth_token_key, "").strip()
            if not default_model or not auth_value:
                # Skip workers that are not yet AI-shaped.
                continue
            models: list[str] = []
            for model in (default_model, *worker.models):
                if model not in models:
                    models.append(model)
            base_url_value = env.get(base_url_key, "").strip() if base_url_key else ""
            # ``auth_value`` may be a ${VAR} reference; the dispatch.yaml
            # loader has already resolved it via the env, but we only want
            # to record the *name*. If the resolved value is non-empty, we
            # treat the env-var name as the canonical key. (Operators who
            # put a literal token here are doing it wrong; we do not
            # paper over that — they will see it in the UI.)
            api_key_env_name = auth_token_key
            # The protocol model expects ``api_key_env`` to be a *name*,
            # not a value; for dispatch.yaml-seeded profiles the canonical
            # name for the worker type is the env-var key itself.
            result.append({
                "name": worker.name,
                "worker_type": worker.type,
                "model": default_model,
                "models": models,
                "base_url": base_url_value,
                "api_key_env": api_key_env_name,
                "provider": "",
                "model_reasoning_effort": worker.model_reasoning_effort,
                # The dispatcher already has the resolved token in
                # ``auth_value`` (post-interpolation). Push it into the
                # server DB so the worker container does not have to
                # round-trip ``os.environ`` at task-launch time.
                "sk": auth_value,
            })
        return result

    def _validate_server_settings(self) -> None:
        settings = self.client.get_settings()
        interval = self.config.runtime.interval
        for name, value in (("intent_timeout", settings.intent_timeout), ("reason_timeout", settings.reason_timeout)):
            if value <= interval:
                raise RuntimeError(
                    f"server {name}={value}s must be greater than dispatcher interval={interval}s"
                )
            if value < interval * 2:
                LOG.warning(
                    "server %s is tight %s=%ss interval=%ss; heartbeat slack is only %ss",
                    name,
                    name,
                    value,
                    interval,
                    value - interval,
                )
                continue
            LOG.info(
                "server setting validated %s=%ss interval=%ss",
                name,
                value,
                interval,
            )

    def _run_startup_healthchecks(self, *, show_commands: bool) -> None:
        results = run_startup_healthchecks(self.config, self.container_manager, show_commands=show_commands)
        if any(result.ok for result in results):
            return
        raise RuntimeError(format_failure_summary(results))
