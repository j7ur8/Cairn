from fastapi import APIRouter

from cairn.server import db
from cairn.server.models_pkg.intents import CreateHintRequest
from cairn.server.models_pkg.projects import Hint
from cairn.server.repositories import sql
from cairn.server.services import check_project_hint_writable, next_hint_id, utcnow

router = APIRouter(tags=["hints"])


@router.post(
    "/projects/{project_id}/hints",
    response_model=Hint,
    status_code=201,
)
def create_hint(project_id: str, body: CreateHintRequest):
    with db.session_scope() as conn:
        check_project_hint_writable(conn, project_id)

        now = utcnow()
        hid = next_hint_id(conn, project_id)
        sql.execute(
            conn,
            """
            INSERT INTO hints (id, project_id, content, creator, created_at)
            VALUES (:id, :project_id, :content, :creator, :created_at)
            """,
            {
                "id": hid,
                "project_id": project_id,
                "content": body.content,
                "creator": body.creator,
                "created_at": now,
            },
        )
        return Hint(id=hid, content=body.content, creator=body.creator, created_at=now)
