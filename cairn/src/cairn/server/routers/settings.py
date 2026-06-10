from fastapi import APIRouter

from cairn.server.models_pkg.common import Settings
from cairn.server.config.settings import get_yaml_settings, update_yaml_settings

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=Settings)
def get_settings():
    return get_yaml_settings()


@router.put("/settings", response_model=Settings)
def update_settings(body: Settings):
    return update_yaml_settings(body)
