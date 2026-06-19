from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from cairn.server import db
from cairn.server.application.project_io import (
    download_project_file as download_project_file_query,
)
from cairn.server.application.project_io import (
    list_project_files as list_project_files_query,
)
from cairn.server.schemas.projects import ProjectFilesResponse
from cairn.server.security.paths import validate_relative_path

router = APIRouter(tags=["files"])


# Path validation lives in cairn.server.security.paths; this
# module re-exports the canonical helper under the historic name so
# any callers that imported the private helper keep working.
_safe_relative_path = validate_relative_path


@router.get("/projects/{project_id}/files", response_model=ProjectFilesResponse)
def list_project_files(project_id: str):
    with db.session_scope() as conn:
        return list_project_files_query(conn, project_id)


@router.get("/projects/{project_id}/files/download")
def download_project_file(
    project_id: str,
    source: str = Query(..., pattern="^(project|attachment)$"),
    path: str = Query(..., min_length=1),
):
    with db.session_scope() as conn:
        target = download_project_file_query(conn, project_id, source, path)
    return FileResponse(
        target.path,
        media_type=target.media_type,
        filename=target.filename,
        # The FileResponse ``content_disposition_type`` controls the
        # disposition header that ships with the response. We override
        # it to ``attachment`` for any HTML/SVG payload to neutralize
        # a stored-XSS pivot that would otherwise render attacker-
        # controlled HTML inside the SPA.
        content_disposition_type=target.content_disposition_type,
    )
