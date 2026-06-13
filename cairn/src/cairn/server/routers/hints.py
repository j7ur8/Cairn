from fastapi import APIRouter

from cairn.server import db
from cairn.server.application.project_io import create_hint as create_hint_command
from cairn.server.models_pkg import CreateHintRequest
from cairn.shared.contracts import Hint

router = APIRouter(tags=["hints"])


@router.post(
    "/projects/{project_id}/hints",
    response_model=Hint,
    status_code=201,
)
def create_hint(project_id: str, body: CreateHintRequest):
    with db.session_scope() as conn:
        return create_hint_command(conn, project_id, body)
