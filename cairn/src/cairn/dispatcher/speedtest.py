"""In-process HTTP health probe for AI profiles (cc-switch speedtest pattern).

No Docker containers — HTTP requests are sent directly from the dispatcher
process.  Each profile gets a two-request probe:

1. **Warm-up**  — HTTP HEAD to the models endpoint (connection reuse, discarded).
2. **Latency**   — HTTP GET to the models endpoint, measured in milliseconds.

This probes *only* base URL reachability; it does not send real LLM requests.
Results are classified by error type: timeout / connect / http_4xx / http_5xx /
parse / none.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from cairn.shared.contracts.ai_profiles import AiProfile

DEFAULT_TIMEOUT_SECS = 20
MIN_TIMEOUT_SECS = 5
MAX_TIMEOUT_SECS = 60


@dataclass
class SpeedtestResult:
    profile_id: str
    ok: bool
    latency_ms: int | None = None
    http_status: int | None = None
    error_type: str | None = None
    error_message: str | None = None


class SpeedtestService:
    """Stateless in-process HTTP health probe for AI profiles."""

    def test_profile(
        self,
        profile: AiProfile,
        secret: str,
        *,
        timeout_secs: float | None = None,
    ) -> SpeedtestResult:
        """Run the two-request speedtest and return a structured result."""
        base_url = (profile.base_url or "").strip().rstrip("/")
        if not base_url:
            return _err(profile.id, None, "connect", "base_url is empty")

        timeout = _sanitize_timeout(timeout_secs or profile.healthcheck_timeout or DEFAULT_TIMEOUT_SECS)
        client = _build_client(timeout)

        try:
            models_url, headers = _endpoint_and_headers(profile, secret, base_url)

            # --- warm-up (discard) ---
            try:
                client.head(models_url, headers=headers)
            except Exception:
                pass  # deliberately discard

            # --- latency probe ---
            latency_ms, http_status = _probe_latency(client, models_url, headers)

            error_type = _classify(http_status)
            ok = error_type is None  # reachable with non-5xx, non-error status

            return SpeedtestResult(
                profile_id=profile.id,
                ok=ok,
                latency_ms=latency_ms,
                http_status=http_status,
                error_type=error_type,
                error_message=None if ok else f"HTTP {http_status}",
            )

        except httpx.TimeoutException:
            return _err(profile.id, None, "timeout", "request timed out")
        except httpx.ConnectError as exc:
            return _err(profile.id, None, "connect", f"connection failed: {exc}")
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            return _err(profile.id, code, _classify(code) or f"http_{code // 100}xx", f"HTTP {code}: {exc}")
        except Exception as exc:
            return _err(profile.id, None, "parse", str(exc))
        finally:
            client.close()


def bulk_speedtest(
    profiles: list[tuple[AiProfile, str]],
    *,
    max_concurrency: int = 8,
) -> list[SpeedtestResult]:
    """Run speedtests concurrently via ThreadPoolExecutor (matching the dispatcher
    architecture).  Each tuple is ``(profile, secret)``."""
    from concurrent.futures import Future, ThreadPoolExecutor, as_completed

    if not profiles:
        return []

    svc = SpeedtestService()
    results: list[SpeedtestResult] = []

    with ThreadPoolExecutor(max_workers=max(1, min(max_concurrency, len(profiles)))) as pool:
        future_map: dict[Future[SpeedtestResult], str] = {}
        for profile, secret in profiles:
            fut = pool.submit(
                svc.test_profile, profile, secret,
                timeout_secs=profile.healthcheck_timeout,
            )
            future_map[fut] = profile.id

        for fut in as_completed(future_map):
            try:
                results.append(fut.result())
            except Exception as exc:
                pid = future_map[fut]
                results.append(_err(pid, None, "parse", f"speedtest crashed: {exc}"))

    return results


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sanitize_timeout(seconds: float) -> float:
    return max(MIN_TIMEOUT_SECS, min(seconds, MAX_TIMEOUT_SECS))


def _build_client(timeout_secs: float) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_secs), follow_redirects=True)


def _endpoint_and_headers(
    profile: AiProfile, secret: str, base_url: str
) -> tuple[str, dict[str, str]]:
    """Returns ``(models_url, headers)`` for the given profile type.

    cc-switch does NOT send auth headers during speedtest — it only probes
    base URL reachability.  We send auth so the models endpoint returns a
    meaningful status code rather than a blanket 401.
    """
    if profile.worker_type == "claudecode":
        return (
            f"{base_url}/v1/models",
            {"x-api-key": secret, "anthropic-version": "2023-06-01"},
        )
    # codex / OpenAI-compatible
    return (
        f"{base_url}/models",
        {"Authorization": f"Bearer {secret}"},
    )


def _probe_latency(
    client: httpx.Client, url: str, headers: dict[str, str]
) -> tuple[int | None, int | None]:
    start = time.monotonic()
    try:
        resp = client.get(url, headers=headers)
        elapsed = int((time.monotonic() - start) * 1000)
        return elapsed, resp.status_code
    except Exception:
        return None, None


def _classify(http_status: int | None) -> str | None:
    if http_status is None:
        return "connect"
    if http_status >= 500:
        return f"http_{http_status // 100}xx"
    return None


def _err(
    profile_id: str,
    http_status: int | None,
    error_type: str,
    error_message: str,
) -> SpeedtestResult:
    return SpeedtestResult(
        profile_id=profile_id,
        ok=False,
        http_status=http_status,
        error_type=error_type,
        error_message=error_message[:1000],
    )
