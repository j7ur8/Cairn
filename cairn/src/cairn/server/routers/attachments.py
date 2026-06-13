from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from cairn.server import db
from cairn.server.application.project_io import (
    IncomingAttachment,
    cleanup_paths,
    verify_attachments_writable,
    write_attachment_files,
)
from cairn.server.application.project_io import (
    upload_project_attachments as upload_project_attachments_command,
)
from cairn.server.models_pkg.projects import AttachmentUploadResponse

router = APIRouter(tags=["attachments"])


@router.post(
    "/projects/{project_id}/attachments",
    response_model=AttachmentUploadResponse,
    status_code=201,
)
def upload_project_attachments(
    project_id: str,
    files: Annotated[list[UploadFile], File(...)],
    descriptions: Annotated[list[str] | None, Form()] = None,
    creator: Annotated[str, Form()] = "Human",
):
    if not files:
        raise HTTPException(400, "No files uploaded")

    creator = creator.strip() or "Human"
    with db.session_scope() as conn:
        verify_attachments_writable(conn, project_id)

    written_paths = []
    try:
        uploaded, written_paths = write_attachment_files(
            project_id,
            [IncomingAttachment(filename=upload.filename, file=upload.file) for upload in files],
            descriptions,
        )
    except Exception:
        cleanup_paths(written_paths)
        raise
    finally:
        for upload in files:
            upload.file.close()

    try:
        with db.session_scope() as conn:
            return upload_project_attachments_command(
                conn,
                project_id,
                uploaded=uploaded,
                creator=creator,
            )
    except Exception:
        cleanup_paths(written_paths)
        raise
