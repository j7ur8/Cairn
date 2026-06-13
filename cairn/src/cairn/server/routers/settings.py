from fastapi import APIRouter, Depends

from cairn.server.config.settings import get_yaml_settings, get_yaml_task_timeouts, update_yaml_settings
from cairn.server.models_pkg.common import Settings
from cairn.server.security.deps import current_active_superuser
from cairn.shared.contracts import TaskTimeouts

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=Settings)
def get_settings():
    return get_yaml_settings()


@router.put("/settings", response_model=Settings)
def update_settings(body: Settings, _superuser=Depends(current_active_superuser)):
    return update_yaml_settings(body)


@router.get("/task-timeouts/defaults", response_model=TaskTimeouts)
def get_task_timeout_defaults():
    return get_yaml_task_timeouts()
