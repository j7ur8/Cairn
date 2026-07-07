from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

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

from cairn.dispatcher.runtime.docker_labels import (
    LABEL_KIND,
    LABEL_MANAGED,
    LABEL_PROJECT_ID,
    LABEL_TOOL,
    tool_sidecar_container_name,
)
from cairn.dispatcher.runtime.mounts import docker_volumes
from cairn.dispatcher.runtime.workspace_preflight import WorkspacePreflight
from cairn.shared.config import ToolSidecarConfig, ToolSidecarsConfig

LOG = logging.getLogger(__name__)

ToolSidecarName = Literal["kali", "metasploit"]
TOOL_SIDECAR_KIND = "tool-sidecar"


@dataclass(slots=True)
class ToolSidecarStatus:
    project_id: str
    tool: str
    container_name: str
    running: bool = False
    enabled: bool = False
    state: str = "disabled"
    error: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "tool": self.tool,
            "container_name": self.container_name,
            "running": self.running,
            "enabled": self.enabled,
            "state": self.state,
            "error": self.error,
        }


def tool_sidecar_name(project_id: str, tool: str) -> str:
    return tool_sidecar_container_name(project_id, tool)


class ToolSidecarManager:
    def __init__(self, config: ToolSidecarsConfig | None, *, client: Any | None = None) -> None:
        self.config = config or ToolSidecarsConfig()
        self._owns_client = client is None
        if client is not None:
            self.client = client
        elif docker is not None:
            self.client = docker.from_env()
        else:
            self.client = None
        self._preflight = WorkspacePreflight(
            access=_WorkspaceAccess(self),
            docker_exception_type=DockerException,
        )

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def ensure_running(self, project_id: str, tool: ToolSidecarName) -> ToolSidecarStatus:
        config = self._tool_config(tool)
        name = tool_sidecar_name(project_id, tool)
        if config is None or not config.enabled:
            raise RuntimeError(f"{tool} tool sidecar is not enabled")
        if self.client is None:
            raise RuntimeError("Docker SDK is required for tool sidecar runtime")
        status = self.status(project_id, tool)
        if status.running:
            self._preflight.run(name, project_id, config.as_container_config())
            return status
        container_config = config.as_container_config()
        labels = {
            LABEL_MANAGED: "true",
            LABEL_KIND: TOOL_SIDECAR_KIND,
            LABEL_TOOL: tool,
            LABEL_PROJECT_ID: project_id,
        }
        try:
            self.client.containers.run(
                container_config.image,
                _sidecar_command(tool),
                detach=True,
                name=name,
                network_mode=container_config.network_mode,
                cap_add=container_config.cap_add or None,
                volumes=docker_volumes(container_config, project_id) or None,
                user=container_config.user,
                labels=labels,
                mem_limit=container_config.mem_limit,
                pids_limit=container_config.pids_limit,
                nano_cpus=container_config.nano_cpus,
            )
        except APIError as exc:
            if not _is_name_conflict(exc):
                raise RuntimeError(f"failed to create {tool} tool sidecar {name}: {exc}") from exc
            container = self.client.containers.get(name)
            container.start()
        except DockerException as exc:
            raise RuntimeError(f"failed to create {tool} tool sidecar {name}: {exc}") from exc
        self._preflight.run(name, project_id, container_config)
        return self.status(project_id, tool)

    def status(self, project_id: str, tool: ToolSidecarName) -> ToolSidecarStatus:
        config = self._tool_config(tool)
        name = tool_sidecar_name(project_id, tool)
        status = ToolSidecarStatus(
            project_id=project_id,
            tool=tool,
            container_name=name,
            enabled=bool(config and config.enabled),
            state="stopped" if config and config.enabled else "disabled",
        )
        if config is None or not config.enabled:
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
        return status

    def cleanup_project(self, project_id: str, *, remove: bool = True) -> bool:
        success = True
        for tool in ("kali", "metasploit"):
            success = self._cleanup_one(project_id, tool, remove=remove) and success
        return success

    def cleanup_orphan(self, container_name: str) -> bool:
        if self.client is None:
            return False
        container = self._get_container(container_name)
        if container is None:
            return True
        try:
            container.remove(force=True)
            return True
        except DockerException as exc:
            LOG.warning("failed to remove orphan tool sidecar container=%s error=%s", container_name, exc)
            return False

    def managed_container_names(self) -> list[str]:
        if self.client is None:
            return []
        try:
            containers = self.client.containers.list(
                all=True,
                filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_KIND}={TOOL_SIDECAR_KIND}"]},
            )
        except DockerException as exc:
            LOG.warning("failed to list tool sidecars error=%s", exc)
            return []
        return sorted(str(container.name) for container in containers)

    def _cleanup_one(self, project_id: str, tool: str, *, remove: bool) -> bool:
        if self.client is None:
            return False
        name = tool_sidecar_name(project_id, tool)
        container = self._get_container(name)
        if container is None:
            return True
        try:
            if remove:
                container.remove(force=True)
            else:
                container.stop(timeout=1)
            return True
        except DockerException as exc:
            LOG.warning("failed to cleanup tool sidecar container=%s error=%s", name, exc)
            return False

    def _tool_config(self, tool: str) -> ToolSidecarConfig | None:
        if tool == "kali":
            return self.config.kali
        if tool == "metasploit":
            return self.config.metasploit
        raise RuntimeError(f"unknown tool sidecar: {tool}")

    def _get_container(self, name: str):
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None
        except DockerException as exc:
            raise RuntimeError(f"failed to get tool sidecar {name}: {exc}") from exc


class _WorkspaceAccess:
    def __init__(self, manager: ToolSidecarManager) -> None:
        self.manager = manager

    def require_container(self, name: str):
        container = self.manager._get_container(name)
        if container is None:
            raise RuntimeError(f"tool sidecar container not found: {name}")
        return container


def _sidecar_command(tool: str) -> list[str]:
    if tool == "kali":
        return ["/usr/local/bin/kali-mcp-http-sidecar"]
    if tool == "metasploit":
        return ["/usr/local/bin/metasploit-mcp-http-sidecar"]
    raise RuntimeError(f"unknown tool sidecar: {tool}")


def _is_name_conflict(exc: Exception) -> bool:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    explanation = str(getattr(exc, "explanation", "") or exc)
    return status_code == 409 or "is already in use" in explanation
