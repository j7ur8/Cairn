from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cairn.shared.config import McpServerCapabilityConfig, RuntimeProviderConfig


class BrowserLeaseWriter(Protocol):
    def write_text_file(self, container_name: str, path: str, content: str) -> None: ...


class CloakBrowserManager(Protocol):
    def lease_browser(self, project_id: str, *, task_instance_id: str, network_mode: str) -> dict[str, Any]: ...

    def release_browser(self, *, control_url: str, lease_id: str) -> None: ...


@dataclass(slots=True)
class BrowserRuntimeLease:
    browser_url: str
    release_env: dict[str, str]
    lease_payload: dict[str, Any]
    sidecar: dict[str, Any] | None = None
    _manager: CloakBrowserManager | None = None

    def release(self) -> None:
        if self._manager is None:
            return
        self._manager.release_browser(
            control_url=str(self.lease_payload.get("control_url") or ""),
            lease_id=str(self.lease_payload.get("lease_id") or ""),
        )


@dataclass(slots=True)
class BrowserRuntimeContext:
    project_id: str
    task_instance_id: str
    network_mode: str
    cloak_sidecar_manager: CloakBrowserManager | None
    container_name: str | None = None
    lease_writer: BrowserLeaseWriter | None = None
    lease_root: str = "/tmp/cairn-browser-leases"

    def acquire(self, mcp: McpServerCapabilityConfig) -> BrowserRuntimeLease | None:
        provider = mcp.runtime_provider
        if not needs_browser_runtime(provider):
            return None
        if provider.type != "cloak_sidecar":
            raise RuntimeError(f"unsupported runtime_provider type: {provider.type}")
        if self.cloak_sidecar_manager is None:
            raise RuntimeError("cloak sidecar runtime provider is unavailable")
        payload = self.cloak_sidecar_manager.lease_browser(
            self.project_id,
            task_instance_id=self.task_instance_id,
            network_mode=self.network_mode,
        )
        browser_url = str(payload.get("browser_url") or "").strip()
        if not browser_url:
            raise RuntimeError("runtime provider did not return browser_url")
        release_env = {
            "CAIRN_BROWSER_LEASE_CONTROL_URL": str(payload.get("control_url") or ""),
            "CAIRN_BROWSER_LEASE_ID": str(payload.get("lease_id") or ""),
        }
        if self.container_name and self.lease_writer:
            lease_file = f"{self.lease_root.rstrip('/')}/{mcp.id}.json"
            try:
                self.lease_writer.write_text_file(
                    self.container_name,
                    lease_file,
                    json.dumps(
                        {
                            "provider": provider.model_dump(),
                            "browser_url": browser_url,
                            "control_url": release_env["CAIRN_BROWSER_LEASE_CONTROL_URL"],
                            "lease_id": release_env["CAIRN_BROWSER_LEASE_ID"],
                        },
                        separators=(",", ":"),
                    ),
                )
            except Exception:
                self.cloak_sidecar_manager.release_browser(
                    control_url=release_env["CAIRN_BROWSER_LEASE_CONTROL_URL"],
                    lease_id=release_env["CAIRN_BROWSER_LEASE_ID"],
                )
                raise
            release_env["CAIRN_BROWSER_LEASE_FILE"] = lease_file
        else:
            temp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="cairn-browser-lease-", suffix=".json")
            with temp:
                json.dump(
                    {
                        "provider": provider.model_dump(),
                        "browser_url": browser_url,
                        "control_url": release_env["CAIRN_BROWSER_LEASE_CONTROL_URL"],
                        "lease_id": release_env["CAIRN_BROWSER_LEASE_ID"],
                    },
                    temp,
                    separators=(",", ":"),
                )
            release_env["CAIRN_BROWSER_LEASE_FILE"] = temp.name
        return BrowserRuntimeLease(
            browser_url=browser_url,
            release_env=release_env,
            lease_payload=payload,
            sidecar=payload.get("sidecar") if isinstance(payload.get("sidecar"), dict) else None,
            _manager=self.cloak_sidecar_manager,
        )


def needs_browser_runtime(provider: RuntimeProviderConfig | None) -> bool:
    return provider is not None and provider.resource == "browser_url"


def render_browser_runtime(
    value: Any,
    *,
    browser_url: str,
) -> Any:
    if isinstance(value, str):
        return value.replace("{browser_url}", browser_url)
    if isinstance(value, list):
        return [render_browser_runtime(item, browser_url=browser_url) for item in value]
    if isinstance(value, dict):
        return {
            key: render_browser_runtime(item, browser_url=browser_url)
            for key, item in value.items()
        }
    return value


def remove_temp_lease_file(lease: BrowserRuntimeLease | None) -> None:
    if lease is None:
        return
    path = lease.release_env.get("CAIRN_BROWSER_LEASE_FILE")
    if not path or not path.startswith("/tmp/cairn-browser-lease-"):
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
