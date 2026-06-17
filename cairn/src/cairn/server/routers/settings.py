from fastapi import APIRouter

from cairn.server.config.settings import get_yaml_task_timeouts
from cairn.shared.contracts import TaskTimeouts

router = APIRouter(tags=["settings"])


@router.get("/task-timeouts/defaults", response_model=TaskTimeouts)
def get_task_timeout_defaults():
    return get_yaml_task_timeouts()
