from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

try:
    import docker
    from docker.errors import APIError, DockerException, NotFound
except ModuleNotFoundError:  # Allows server imports without Docker SDK in minimal environments.
    docker = None

    class DockerException(Exception):  # type: ignore[no-redef]
        pass

    class APIError(DockerException):  # type: ignore[no-redef]
        pass

    class NotFound(DockerException):  # type: ignore[no-redef]
        pass

from cairn.dispatcher.runtime.docker_labels import LABEL_MANAGED, LABEL_PROJECT_ID, safe_project_id
from cairn.shared.config import CloakSidecarConfig

LOG = logging.getLogger(__name__)

CLOAK_CONTAINER_PREFIX = "cairn-cloak-"
LABEL_CLOAK_SIDECAR = "cairn.cloak_sidecar"
CONTROL_PORT = 7310
NOVNC_PORT = 6080
CDP_BASE_PORT = 9222
CONTROL_READY_TIMEOUT_SECONDS = 20.0
SLOT_READY_TIMEOUT_SECONDS = 90.0
CONTROL_READY_POLL_SECONDS = 0.25
CONTROL_HEALTH_TIMEOUT_SECONDS = 1.0
CLOAK_CONTROL_NO_PROXIES = {"http": None, "https": None, "all": None}


@dataclass(slots=True)
class CloakSidecarStatus:
    project_id: str
    container_name: str
    running: bool = False
    enabled: bool = False
    novnc_url: str | None = None
    slots: int = 0
    busy_slots: int = 0
    ready: bool = False
    state: str = "disabled"
    error: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "container_name": self.container_name,
            "running": self.running,
            "enabled": self.enabled,
            "novnc_url": self.novnc_url,
            "slots": self.slots,
            "busy_slots": self.busy_slots,
            "ready": self.ready,
            "state": self.state,
            "error": self.error,
        }


def cloak_container_name(project_id: str) -> str:
    return f"{CLOAK_CONTAINER_PREFIX}{safe_project_id(project_id)}"


class CloakSidecarManager:
    def __init__(self, config: CloakSidecarConfig | None, *, client: Any | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        if client is not None:
            self.client = client
        elif docker is not None:
            self.client = docker.from_env()
        else:
            self.client = None

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def ensure_running(self, project_id: str, *, network_mode: str) -> CloakSidecarStatus:
        status = self.status(project_id)
        if self.config is None:
            raise RuntimeError("cloak sidecar config missing")
        if self.client is None:
            raise RuntimeError("Docker SDK is required for cloak sidecar runtime")
        if status.running:
            return status
        name = cloak_container_name(project_id)
        profile_root = Path(self.config.profile_root) / project_id
        profile_root.mkdir(parents=True, exist_ok=True)
        labels = {
            LABEL_MANAGED: "true",
            LABEL_CLOAK_SIDECAR: "true",
            LABEL_PROJECT_ID: project_id,
        }
        environment = {
            "CAIRN_CLOAK_SLOTS": str(self.config.slots),
            "CAIRN_CLOAK_CDP_BASE_PORT": str(CDP_BASE_PORT),
            "CAIRN_CLOAK_CONTROL_PORT": str(CONTROL_PORT),
            "CAIRN_CLOAK_NOVNC_PORT": str(NOVNC_PORT),
            "CAIRN_CLOAK_PUBLIC_HOST": name,
        }
        ports = {f"{NOVNC_PORT}/tcp": (self.config.novnc.host, None)} if self.config.novnc.enabled else None
        try:
            self.client.containers.run(
                self.config.image,
                detach=True,
                name=name,
                network_mode=network_mode,
                volumes={str(profile_root): {"bind": "/profiles", "mode": "rw"}},
                labels=labels,
                environment=environment,
                ports=ports,
                shm_size="1g",
            )
        except APIError as exc:
            if not self._is_name_conflict(exc):
                raise RuntimeError(f"failed to create cloak sidecar {name}: {exc}") from exc
            container = self.client.containers.get(name)
            container.start()
        except DockerException as exc:
            raise RuntimeError(f"failed to create cloak sidecar {name}: {exc}") from exc
        return self._wait_for_control_service(project_id, name)

    def lease_browser(
        self,
        project_id: str,
        *,
        task_instance_id: str,
        network_mode: str,
    ) -> dict[str, Any]:
        status = self.ensure_running(project_id, network_mode=network_mode)
        if not status.running:
            raise RuntimeError(status.error or f"cloak sidecar not running: {status.container_name}")
        lease_id = f"{task_instance_id}-{project_id}"
        control_url = f"http://{cloak_container_name(project_id)}:{CONTROL_PORT}"
        control_status = self._wait_for_browser_slot(project_id, status.container_name)
        if not control_status.running:
            raise RuntimeError(control_status.error or f"cloak sidecar not running: {control_status.container_name}")
        if control_status.error.startswith("health unavailable:"):
            raise RuntimeError(
                f"cloak sidecar control service unavailable at {control_url}: {control_status.error}"
            )
        if control_status.state == "error" and control_status.error:
            raise RuntimeError(f"cloak sidecar browser slot unavailable at {control_url}: {control_status.error}")
        try:
            response = requests.post(
                f"{control_url}/lease",
                json={"lease_id": lease_id},
                timeout=35.0,
                proxies=CLOAK_CONTROL_NO_PROXIES,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"failed to lease CloakBrowser slot from {control_url}: {exc}") from exc
        browser_url = str(data.get("browser_url") or "").strip() if isinstance(data, dict) else ""
        if not browser_url:
            raise RuntimeError(f"CloakBrowser lease from {control_url} did not return browser_url")
        return {
            "browser_url": browser_url,
            "lease_id": str(data.get("lease_id") or lease_id),
            "control_url": control_url,
            "sidecar": control_status.model_dump(),
        }

    def release_browser(self, *, control_url: str, lease_id: str) -> None:
        if not control_url or not lease_id:
            return
        try:
            requests.post(
                f"{control_url.rstrip('/')}/release",
                json={"lease_id": lease_id},
                timeout=2.0,
                proxies=CLOAK_CONTROL_NO_PROXIES,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("failed to release cloak browser lease=%s control_url=%s error=%s", lease_id, control_url, exc)

    def status(self, project_id: str) -> CloakSidecarStatus:
        name = cloak_container_name(project_id)
        status = CloakSidecarStatus(
            project_id=project_id,
            container_name=name,
            enabled=self.config is not None,
            slots=self.config.slots if self.config is not None else 0,
            state="stopped" if self.config is not None else "disabled",
        )
        if self.config is None:
            return status
        if self.client is None:
            status.error = "docker unavailable"
            return status
        container = self._get_container(name)
        if container is None:
            return status
        try:
            container.reload()
        except DockerException as exc:
            status.error = str(exc)
            return status
        state = str(container.attrs.get("State", {}).get("Status") or "")
        status.running = state == "running"
        status.state = state or ("running" if status.running else "stopped")
        status.novnc_url = self._novnc_url(container) if status.running else None
        if status.running:
            self._merge_health(project_id, status)
        return status

    def cleanup_project(self, project_id: str, *, remove: bool) -> bool:
        if self.config is None or self.client is None:
            return False
        name = cloak_container_name(project_id)
        container = self._get_container(name)
        if container is None:
            return False
        try:
            if remove:
                container.remove(force=True)
            else:
                container.stop(timeout=1)
            return True
        except DockerException as exc:
            LOG.warning("failed to cleanup cloak sidecar container=%s error=%s", name, exc)
            return False

    def cleanup_orphan(self, container_name: str) -> bool:
        if self.client is None:
            return False
        container = self._get_container(container_name)
        if container is None:
            return False
        try:
            container.remove(force=True)
            return True
        except DockerException as exc:
            LOG.warning("failed to remove orphan cloak sidecar container=%s error=%s", container_name, exc)
            return False

    def managed_container_names(self) -> list[str]:
        if self.client is None:
            return []
        try:
            containers = self.client.containers.list(
                all=True,
                filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_CLOAK_SIDECAR}=true"]},
            )
        except DockerException as exc:
            LOG.warning("failed to list cloak sidecars error=%s", exc)
            return []
        return [str(container.name) for container in containers]

    def _get_container(self, name: str):
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None
        except DockerException as exc:
            raise RuntimeError(f"failed to get cloak sidecar {name}: {exc}") from exc

    def _merge_health(self, project_id: str, status: CloakSidecarStatus) -> None:
        url = f"http://{cloak_container_name(project_id)}:{CONTROL_PORT}/healthz"
        try:
            response = requests.get(url, timeout=CONTROL_HEALTH_TIMEOUT_SECONDS, proxies=CLOAK_CONTROL_NO_PROXIES)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            status.error = f"health unavailable: {exc}"
            return
        status.ready = bool(data.get("ready"))
        if isinstance(data.get("state"), str) and data.get("state"):
            status.state = str(data["state"])
        if isinstance(data.get("error"), str):
            status.error = str(data.get("error") or "")
        slots = data.get("slots")
        if isinstance(slots, list):
            status.slots = len(slots)
            status.busy_slots = sum(1 for slot in slots if isinstance(slot, dict) and slot.get("busy"))
            if not status.error:
                errors = [
                    f"slot {slot.get('slot')}: {slot.get('error')}"
                    for slot in slots
                    if isinstance(slot, dict) and slot.get("error")
                ]
                status.error = "; ".join(errors)

    def _wait_for_control_service(self, project_id: str, name: str) -> CloakSidecarStatus:
        deadline = time.monotonic() + CONTROL_READY_TIMEOUT_SECONDS
        last_status = self.status(project_id)
        while True:
            error = str(last_status.error or "")
            if last_status.running and not error.startswith("health unavailable:"):
                return last_status
            if not last_status.running:
                last_status.error = last_status.error or f"cloak sidecar exited before control service became ready: {name}"
                return last_status
            if time.monotonic() >= deadline:
                last_status.error = (
                    error
                    or f"cloak sidecar control service did not become ready within {CONTROL_READY_TIMEOUT_SECONDS:g}s: {name}"
                )
                return last_status
            time.sleep(CONTROL_READY_POLL_SECONDS)
            last_status = self.status(project_id)

    def _wait_for_browser_slot(self, project_id: str, name: str) -> CloakSidecarStatus:
        deadline = time.monotonic() + SLOT_READY_TIMEOUT_SECONDS
        last_status = self._wait_for_control_service(project_id, name)
        while True:
            error = str(last_status.error or "")
            if not last_status.running or error.startswith("health unavailable:"):
                return last_status
            if last_status.ready or last_status.state not in ("launching", "unavailable"):
                return last_status
            if time.monotonic() >= deadline:
                last_status.error = (
                    error
                    or f"cloak sidecar browser slot did not become ready within {SLOT_READY_TIMEOUT_SECONDS:g}s: {name}"
                )
                return last_status
            time.sleep(CONTROL_READY_POLL_SECONDS)
            last_status = self.status(project_id)

    def _novnc_url(self, container: Any) -> str | None:
        ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
        bindings = ports.get(f"{NOVNC_PORT}/tcp")
        if not bindings:
            return None
        first = bindings[0]
        host_ip = str(first.get("HostIp") or self.config.novnc.host)
        host_port = str(first.get("HostPort") or "")
        if not host_port:
            return None
        if host_ip in ("0.0.0.0", "::"):
            host_ip = "127.0.0.1"
        return f"http://{host_ip}:{host_port}/vnc.html?autoconnect=1&resize=scale"

    @staticmethod
    def _is_name_conflict(exc: Exception) -> bool:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        explanation = str(getattr(exc, "explanation", "") or exc)
        return status_code == 409 or "is already in use" in explanation
