from __future__ import annotations

from typing import Any

from cairn.dispatcher.protocol.base import HttpClientBase
from cairn.dispatcher.protocol.results import ApiResult


class AiProfileApiClient(HttpClientBase):
    def get_ai_profile_secret(self, profile_id: str) -> str | None:
        response = self._get(f"/ai-profiles/{profile_id}/secret")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        value = payload.get("value")
        return value if isinstance(value, str) and value else None

    def list_ai_profiles(self) -> ApiResult:
        return self._get_json_result("/ai-profiles")

    def post_ai_health_report(self, body: dict[str, Any]) -> ApiResult:
        return self._request_json("POST", "/ai-profiles/health-report", json=body)

    def claim_ai_profile_check_request(self) -> ApiResult:
        return self._request_json("POST", "/ai-profiles/check-requests/claim", json={})

    def complete_ai_profile_check_request(self, request_id: str, *, ok: bool, message: str = "") -> ApiResult:
        return self._request_json(
            "POST",
            f"/ai-profiles/check-requests/{request_id}/complete",
            json={"ok": ok, "message": message},
        )
