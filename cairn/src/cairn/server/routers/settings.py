from fastapi import APIRouter

from cairn.server.db import get_conn  # imported for legacy test patch points
from cairn.server.models import Settings
from cairn.server.yaml_config import get_yaml_settings, update_yaml_settings

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=Settings)
def get_settings():
    with get_conn():
        pass
    return get_yaml_settings()


@router.put("/settings", response_model=Settings)
def update_settings(body: Settings):
    return update_yaml_settings(body)
