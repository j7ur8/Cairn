"""System-config CRUD endpoints for the YAML-backed config.yaml sections."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cairn.server.config.runtime_limits import get_container_limits
from cairn.server.config.system_settings import get_system_settings, update_system_settings
from cairn.server.security.deps import current_active_superuser
from cairn.shared.contracts import (
    ContainerLimits,
    SystemSettingsAdmin,
)

router = APIRouter(tags=["system-config"])


# --- Aggregate System settings ---


@router.get("/system-settings", response_model=SystemSettingsAdmin)
def read_system_settings():
    return get_system_settings()


@router.put("/system-settings", response_model=SystemSettingsAdmin)
def write_system_settings(body: SystemSettingsAdmin, _superuser=Depends(current_active_superuser)):
    return update_system_settings(body)


# --- Container limits ---


@router.get("/container-limits", response_model=ContainerLimits)
def read_container_limits():
    return get_container_limits()
