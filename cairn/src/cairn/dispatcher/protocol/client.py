from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging
import threading

from pydantic import TypeAdapter
import requests
from requests.adapters import HTTPAdapter
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from cairn.shared.protocol_models import Settings
from cairn.shared.protocol_models import ReasonState
from cairn.shared.protocol_models import Intent, ProjectDetail, ProjectSummary
from cairn.shared.protocol_models import ProxyConfig

LOG = logging.getLogger(__name__)


class ProtocolError(RuntimeError):
    def __init__(self, message: str, status_code: int, response_text: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


@dataclass(slots=True)
class ApiResult:
    status_code: int
    data: Any | None = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class CairnClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        *,
        api_token: str | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._api_token = api_token or ""
        self._summary_adapter = TypeAdapter(list[ProjectSummary])
        self._local = threading.local()
        self._sessions: dict[int, requests.Session] = {}
        self._sessions_lock = threading.Lock()

    def close(self) -> None:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

    def list_projects(self) -> list[ProjectSummary]:
        response = self._get("/projects")
        response.raise_for_status()
        return self._summary_adapter.validate_python(response.json())

    def get_project(self, project_id: str) -> ProjectDetail:
        response = self._get(f"/projects/{project_id}")
        response.raise_for_status()
        return ProjectDetail.model_validate(response.json())

    def get_settings(self) -> Settings:
        response = self._get("/settings")
        response.raise_for_status()
        return Settings.model_validate(response.json())

    def get_proxy(self, proxy_id: str) -> ProxyConfig:
        """Fetch a proxy definition (with credentials) for worker env injection.

        Called by the dispatcher at task-launch time when the project has a
        ``proxy_id`` set. Returns the full ``ProxyConfig`` including
        ``username`` / ``password`` so the worker can construct authenticated
        proxy URLs.
        """
        response = self._get(f"/proxies/{proxy_id}")
        if response.status_code == 404:
            raise LookupError(f"proxy not found: {proxy_id}")
        response.raise_for_status()
        return ProxyConfig.model_validate(response.json())

    def get_ai_profile_secret(self, profile_id: str) -> str | None:
        """Fetch the raw ``sk`` value for a profile, for worker env injection.

        Returns ``None`` if the profile has no stored sk (operator relies on
        the host env) or the profile id is unknown. Mirrors the
        ``get_proxy`` precedent: sensitive data needed at task-launch
        time is pulled from the server, never carried in the project
        AI selection snapshot.
        """
        response = self._get(f"/ai-profiles/{profile_id}/secret")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        value = payload.get("value")
        return value if isinstance(value, str) and value else None

    def export_project(self, project_id: str) -> str:
        response = self._get(f"/projects/{project_id}/export", params={"format": "yaml"})
        response.raise_for_status()
        return response.text

    def heartbeat(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/heartbeat",
            json={"worker": worker},
        )

    def claim_reason(
        self,
        project_id: str,
        worker: str,
        trigger: str,
        *,
        run_id: str,
        trigger_hash: str,
        fact_count: int,
        hint_count: int,
        open_intent_count: int,
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/claim",
            json={
                "worker": worker,
                "run_id": run_id,
                "trigger": trigger,
                "trigger_hash": trigger_hash,
                "fact_count": fact_count,
                "hint_count": hint_count,
                "open_intent_count": open_intent_count,
            },
        )

    def get_reason_state(self, project_id: str) -> ApiResult:
        result = self._get_json_result(f"/projects/{project_id}/reason/state")
        if result.ok and isinstance(result.data, dict):
            result.data = ReasonState.model_validate(result.data)
        return result

    def finish_reason(
        self,
        project_id: str,
        worker: str,
        *,
        run_id: str,
        trigger: str,
        trigger_hash: str,
        fact_count: int,
        hint_count: int,
        open_intent_count: int,
        outcome: str,
        error: str | None = None,
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/finish",
            json={
                "worker": worker,
                "run_id": run_id,
                "trigger": trigger,
                "trigger_hash": trigger_hash,
                "fact_count": fact_count,
                "hint_count": hint_count,
                "open_intent_count": open_intent_count,
                "outcome": outcome,
                "error": error,
            },
        )

    def reason_heartbeat(self, project_id: str, worker: str, run_id: str | None = None) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/heartbeat",
            json={"worker": worker, "run_id": run_id},
        )

    def release_reason(self, project_id: str, worker: str, run_id: str | None = None) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/release",
            json={"worker": worker, "run_id": run_id},
        )

    def release(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/release",
            json={"worker": worker},
        )

    def conclude(self, project_id: str, intent_id: str, worker: str, description: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/conclude",
            json={"worker": worker, "description": description},
        )

    def complete(self, project_id: str, from_ids: list[str], description: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/complete",
            json={"from": from_ids, "description": description, "worker": worker},
        )

    def create_intent(self, project_id: str, from_ids: list[str], description: str, creator: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents",
            json={"from": from_ids, "description": description, "creator": creator, "worker": None},
        )

    def advance_replay_run(self, project_id: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/replay-runs/advance",
            json={},
        )

    def get_project_execution_config(self, project_id: str, task_type: str) -> ApiResult:
        return self._get_json_result(f"/projects/{project_id}/execution-configs/{task_type}")

    def list_ai_profiles(self) -> ApiResult:
        return self._get_json_result("/ai-profiles")

    def post_ai_health_report(self, body: dict[str, Any]) -> ApiResult:
        return self._request_json("POST", "/ai-profiles/health-report", json=body)

    def post_ai_models_report(self, body: dict[str, Any]) -> ApiResult:
        return self._request_json("POST", "/ai-profiles/models-report", json=body)

    def claim_ai_profile_check_request(self) -> ApiResult:
        return self._request_json("POST", "/ai-profiles/check-requests/claim", json={})

    def complete_ai_profile_check_request(self, request_id: str, *, ok: bool, message: str = "") -> ApiResult:
        return self._request_json(
            "POST",
            f"/ai-profiles/check-requests/{request_id}/complete",
            json={"ok": ok, "message": message},
        )

    def get_project_role(self, project_id: str) -> ApiResult:
        return self._get_json_result(f"/projects/{project_id}/role")

    def dispatcher_lock_acquire(self, name: str, holder: str, ttl_seconds: float) -> ApiResult:
        return self._request_json(
            "POST",
            "/dispatcher-lock/acquire",
            json={"name": name, "holder": holder, "ttl_seconds": ttl_seconds},
        )

    def dispatcher_lock_heartbeat(self, name: str, holder: str) -> ApiResult:
        return self._request_json(
            "POST",
            "/dispatcher-lock/heartbeat",
            json={"name": name, "holder": holder},
        )

    def dispatcher_lock_release(self, name: str, holder: str) -> ApiResult:
        return self._request_json(
            "POST",
            "/dispatcher-lock/release",
            json={"name": name, "holder": holder},
        )

    def dispatcher_lock_current(self, name: str) -> ApiResult:
        return self._get_json_result("/dispatcher-lock/current", params={"name": name})

    def create_llm_execution(
        self,
        project_id: str,
        execution_id: str,
        *,
        intent_id: str | None,
        task_type: str,
        worker: str,
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/llm-executions",
            json={"id": execution_id, "intent_id": intent_id, "task_type": task_type, "worker": worker},
        )

    def create_llm_event(
        self,
        project_id: str,
        execution_id: str,
        *,
        phase: str,
        event_kind: str,
        stream: str,
        content: str,
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/llm-executions/{execution_id}/events",
            json={"phase": phase, "event_kind": event_kind, "stream": stream, "content": content},
        )

    def create_llm_events(
        self,
        project_id: str,
        execution_id: str,
        events: list[dict[str, str]],
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/llm-executions/{execution_id}/events/batch",
            json={"events": events},
        )

    def finish_llm_execution(
        self,
        project_id: str,
        execution_id: str,
        *,
        process_state: str,
        returncode: int | None = None,
        timed_out: bool = False,
        error_kind: str | None = None,
        produced_fact_id: str | None = None,
        created_intent_ids: list[str] | None = None,
    ) -> ApiResult:
        body: dict[str, Any] = {
            "process_state": process_state,
            "returncode": returncode,
            "timed_out": timed_out,
            "error_kind": error_kind,
            "produced_fact_id": produced_fact_id,
            "created_intent_ids": created_intent_ids,
        }
        return self._request_json(
            "POST",
            f"/projects/{project_id}/llm-executions/{execution_id}/finish",
            json=body,
        )

    def _get_json_result(self, path: str, **kwargs: Any) -> ApiResult:
        try:
            response = self._get(path, **kwargs)
        except requests.RequestException as exc:
            LOG.warning("request failed method=GET path=%s error=%s", path, exc)
            return ApiResult(status_code=0, text=str(exc))
        return self._api_result_from_response(response)

    def _request_json(self, method: str, path: str, json: dict[str, Any]) -> ApiResult:
        try:
            response = self._session().request(
                method,
                self._url(path),
                json=json,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            LOG.warning("request failed method=%s path=%s error=%s", method, path, exc)
            return ApiResult(status_code=0, text=str(exc))
        return self._api_result_from_response(response)

    def _api_result_from_response(self, response: requests.Response) -> ApiResult:
        data: Any | None = None
        if response.status_code == 204 or not response.content:
            return ApiResult(status_code=response.status_code, data=data, text=response.text)
        if response.headers.get("content-type", "").startswith("application/json"):
            try:
                data = response.json()
            except ValueError as exc:
                LOG.warning(
                    "json response parse failed status=%s url=%s error=%s",
                    response.status_code,
                    response.url,
                    exc,
                )
        return ApiResult(status_code=response.status_code, data=data, text=response.text)

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.5, max=2.0),
        reraise=True,
    )
    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        """GET with retry for network failures and 5xx responses.

        POST/PUT calls are intentionally *not* retried here because
        many dispatcher writes are not idempotent. GET is safe to
        retry and covers the high-volume polling paths.
        """
        response = self._session().get(
            self._url(path),
            timeout=self._timeout,
            **kwargs,
        )
        if 500 <= response.status_code < 600:
            raise requests.HTTPError(
                f"server returned {response.status_code} for GET {path}",
                response=response,
            )
        return response

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is not None:
            return session

        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, pool_block=False)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        if self._api_token:
            session.headers["Authorization"] = f"Bearer {self._api_token}"
        # Stamp every outbound call with the current trace id so the
        # server can stitch scheduler -> worker -> server logs
        # together. The middleware on the server honors the inbound
        # header and the trace_id_var propagates the same value into
        # every downstream log line.
        try:
            from cairn.observability.trace import get_trace_id
            tid = get_trace_id()
            if tid:
                session.headers["X-Request-Id"] = tid
        except Exception:  # noqa: BLE001 - observability is best-effort
            pass
        self._local.session = session
        with self._sessions_lock:
            self._sessions[threading.get_ident()] = session
        return session
