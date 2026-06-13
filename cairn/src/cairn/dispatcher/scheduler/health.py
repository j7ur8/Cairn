from __future__ import annotations

import logging

from cairn.dispatcher.ai_health import run_profile_worker_healthcheck
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.startup_healthcheck import (
    format_failure_summary,
    run_startup_healthchecks,
)
from cairn.shared.config import DispatchConfig
from cairn.shared.contracts import AiProfile

LOG = logging.getLogger(__name__)


class DispatcherHealthCoordinator:
    def __init__(
        self,
        *,
        config: DispatchConfig,
        client: CairnClient,
        container_manager: ContainerManager,
    ):
        self.config = config
        self.client = client
        self.container_manager = container_manager

    def refresh(
        self,
        *,
        config: DispatchConfig,
        client: CairnClient,
        container_manager: ContainerManager,
    ) -> None:
        self.config = config
        self.client = client
        self.container_manager = container_manager

    def process_ai_profile_check_requests(self) -> None:
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
            self._run_ai_profile_check(request_id, profile_id)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ai profile check failed profile_id=%s error=%s", profile_id, exc)
            try:
                self.client.complete_ai_profile_check_request(
                    request_id, ok=False, message=str(exc)[:1000],
                )
            except Exception:  # noqa: BLE001
                LOG.exception("ai profile check complete failed request_id=%s", request_id)

    def _run_ai_profile_check(self, request_id: str, profile_id: str) -> None:
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

    def validate_server_settings(self) -> None:
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

    def run_startup_healthchecks(self, *, show_commands: bool) -> None:
        results = run_startup_healthchecks(
            self.config,
            self.container_manager,
            show_commands=show_commands,
        )
        if any(result.ok for result in results):
            return
        LOG.warning(format_failure_summary(results))
