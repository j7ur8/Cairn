from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from cairn.server import db
from cairn.server.application.export import (
    export_project_text,
    export_project_timeline,
    export_project_yaml,
)

router = APIRouter(tags=["export"])


_export_yaml = export_project_yaml
_export_timeline = export_project_timeline


@router.get("/projects/{project_id}/export")
def export_project(project_id: str, format: str = "yaml"):
    if format not in ("yaml", "timeline"):
        raise HTTPException(400, "Supported formats: yaml, timeline")

    with db.session_scope() as conn:
        text = export_project_text(conn, project_id, format)
        return Response(content=text, media_type="text/plain")
