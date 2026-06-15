"""System-config CRUD endpoints for the YAML-backed config.yaml sections."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cairn.server.config.observability_config import get_observability, update_observability
from cairn.server.config.runtime_limits import (
    get_container_limits,
    get_runtime_limits,
    update_runtime_limits,
)
from cairn.server.config.system_config_svc import get_server_log_retention, update_server_log_retention
from cairn.server.config.task_timeouts import get_task_timeouts, update_task_timeouts
from cairn.server.security.deps import current_active_superuser
from cairn.shared.contracts import (
    ContainerLimits,
    ObservabilitySettings,
    RuntimeLimits,
    ServerLogRetention,
    TaskTimeouts,
)

router = APIRouter(tags=["system-config"])


# --- Runtime limits ---


@router.get("/runtime-limits", response_model=RuntimeLimits)
def read_runtime_limits():
    return get_runtime_limits()


@router.put("/runtime-limits", response_model=RuntimeLimits)
def write_runtime_limits(body: RuntimeLimits, _superuser=Depends(current_active_superuser)):
    return update_runtime_limits(body)


# --- Container limits ---


@router.get("/container-limits", response_model=ContainerLimits)
def read_container_limits():
    return get_container_limits()


# --- Task timeouts ---


@router.get("/task-timeouts", response_model=TaskTimeouts)
def read_task_timeouts():
    return get_task_timeouts()


@router.put("/task-timeouts", response_model=TaskTimeouts)
def write_task_timeouts(body: TaskTimeouts, _superuser=Depends(current_active_superuser)):
    return update_task_timeouts(body)


# --- Observability ---


@router.get("/observability", response_model=ObservabilitySettings)
def read_observability():
    return get_observability()


@router.put("/observability", response_model=ObservabilitySettings)
def write_observability(body: ObservabilitySettings, _superuser=Depends(current_active_superuser)):
    return update_observability(body)


# --- Server log + retention ---


@router.get("/server-log-retention", response_model=ServerLogRetention)
def read_server_log_retention():
    return get_server_log_retention()


@router.put("/server-log-retention", response_model=ServerLogRetention)
def write_server_log_retention(body: ServerLogRetention, _superuser=Depends(current_active_superuser)):
    return update_server_log_retention(body)
