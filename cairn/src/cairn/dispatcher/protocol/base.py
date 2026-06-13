from __future__ import annotations

import logging
import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from tenacity import retry, retry_if_exception_type, stop_after_attempt

from cairn.dispatcher.protocol.results import ApiResult

try:
    from tenacity import wait_exponential_jitter
except ImportError:  # Older tenacity versions do not expose jitter.
    from tenacity import wait_exponential

    def wait_exponential_jitter(initial: float, max: float):  # type: ignore[no-redef]
        return wait_exponential(multiplier=initial, max=max)


LOG = logging.getLogger(__name__)


class HttpClientBase:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        *,
        api_token: str | None = None,
        observability_timeout: float = 2.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._observability_timeout = observability_timeout
        self._api_token = api_token or ""
        self._local = threading.local()
        self._sessions: dict[int, requests.Session] = {}
        self._sessions_lock = threading.Lock()

    def close(self) -> None:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

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

    def _request_observability_json(self, method: str, path: str, json: dict[str, Any]) -> ApiResult:
        try:
            response = self._session().request(
                method,
                self._url(path),
                json=json,
                timeout=self._observability_timeout,
            )
        except requests.RequestException as exc:
            LOG.debug("observability request failed method=%s path=%s error=%s", method, path, exc)
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
        """GET with retry for network failures and 5xx responses."""
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
        try:
            from cairn.observability.trace import get_trace_id

            trace_id = get_trace_id()
            if trace_id:
                session.headers["X-Request-Id"] = trace_id
        except Exception:  # noqa: BLE001 - observability is best-effort.
            pass
        self._local.session = session
        with self._sessions_lock:
            self._sessions[threading.get_ident()] = session
        return session
