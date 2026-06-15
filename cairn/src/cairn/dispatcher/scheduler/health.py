from __future__ import annotations

import logging

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.speedtest import SpeedtestResult, SpeedtestService, bulk_speedtest
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
        secret = self._resolve_secret(profile)
        result = SpeedtestService().test_profile(profile, secret)
        self._post_result(result)
        self.client.complete_ai_profile_check_request(
            request_id, ok=result.ok, message=result.error_message or "ok",
        )

    def _resolve_secret(self, profile: AiProfile) -> str:
        try:
            return self.client.get_ai_profile_secret(profile.id) or ""
        except Exception as exc:
            LOG.warning("ai profile check: secret lookup failed profile_id=%s error=%s", profile.id, exc)
            return ""

    def _post_result(self, result: SpeedtestResult) -> None:
        self.client.post_ai_health_report({
            "reports": [{
                "profile_id": result.profile_id,
                "ok": result.ok,
                "latency_ms": result.latency_ms,
                "http_status": result.http_status,
                "error_type": result.error_type,
                "message": result.error_message or "",
                "check_type": "manual",
            }],
        })

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
        """Run in-process HTTP speedtests against all AI profiles at startup.

        Replaces the old container-based startup healthcheck (which created
        temporary Docker containers).  Profiles without a base_url are
        skipped (they are seeded from config.yaml workers, not real APIs).
        """
        try:
            response = self.client.list_ai_profiles()
        except Exception as exc:
            LOG.warning("startup health: cannot list ai profiles error=%s", exc)
            return
        if not response.ok or not isinstance(response.data, list):
            return
        profiles: list[tuple[AiProfile, str]] = []
        for raw in response.data:
            if not isinstance(raw, dict):
                continue
            try:
                profile = AiProfile.model_validate(raw)
            except Exception:
                continue
            if not profile.base_url or not profile.base_url.strip():
                LOG.debug("startup health: skipping profile_id=%s (no base_url)", profile.id)
                continue
            secret = self._resolve_secret(profile)
            if not secret:
                LOG.info("startup health: skipping profile_id=%s (no secret)", profile.id)
                continue
            profiles.append((profile, secret))
        if not profiles:
            LOG.info("startup health: no profiles with base_url to check")
            return
        results = bulk_speedtest(profiles)
        reports = [
            {
                "profile_id": r.profile_id,
                "ok": r.ok,
                "latency_ms": r.latency_ms,
                "http_status": r.http_status,
                "error_type": r.error_type,
                "message": r.error_message or "",
                "check_type": "startup",
            }
            for r in results
        ]
        try:
            self.client.post_ai_health_report({"reports": reports})
        except Exception as exc:
            LOG.warning("startup health: post failed error=%s", exc)
        ok_count = sum(1 for r in results if r.ok)
        fail_count = len(results) - ok_count
        LOG.info("startup health: %d/%d profiles ok, %d failed", ok_count, len(results), fail_count)
        for r in results:
            if not r.ok:
                LOG.warning("startup health FAIL profile_id=%s error_type=%s msg=%s",
                            r.profile_id, r.error_type, r.error_message)
