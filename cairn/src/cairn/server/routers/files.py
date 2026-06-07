from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from cairn.server.db import get_conn
from cairn.server.models import ProjectFileItem, ProjectFilesResponse
from cairn.server.security.paths import (
    download_size_guard,
    force_attachment_disposition,
    safe_resolve_within,
    validate_project_id,
    validate_relative_path,
)
from cairn.server.services import get_project_or_404

router = APIRouter(tags=["files"])

_REPO_ROOT = Path(__file__).resolve().parents[5]
_PROJECT_FILES_ROOT = Path(os.environ.get("CAIRN_PROJECT_FILES_ROOT", str(_REPO_ROOT / "datas" / "project-files")))
_ATTACHMENTS_ROOT = Path(os.environ.get("CAIRN_ATTACHMENTS_ROOT", str(_REPO_ROOT / "datas" / "attachments")))


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Path validation lives in cairn.server.security.paths; this
# module re-exports the canonical helper under the historic name so
# any callers that imported the private helper keep working.
_safe_relative_path = validate_relative_path


def _resolve_project_file(project_id: str, source: str, rel_path: str) -> Path:
    if source == "project":
        root = _PROJECT_FILES_ROOT / project_id
    elif source == "attachment":
        root = _ATTACHMENTS_ROOT / project_id
    else:
        raise HTTPException(400, "source must be project or attachment")

    validate_project_id(project_id)
    rel = _safe_relative_path(rel_path)
    target = safe_resolve_within(root, rel)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return target


def _category(source: str, rel_path: str) -> str:
    if source == "attachment":
        return "attachments"
    first = PurePosixPath(rel_path).parts[0] if PurePosixPath(rel_path).parts else ""
    if first == "reports":
        return "reports"
    if first in ("exploit", "vuln-research"):
        return "exploit"
    return "other"


def _iter_files(root: Path, source: str) -> list[ProjectFileItem]:
    if not root.exists() or not root.is_dir():
        return []
    root_resolved = root.resolve(strict=False)
    items: list[ProjectFileItem] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            target = path.resolve(strict=False)
            if target != root_resolved and root_resolved not in target.parents:
                continue
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
        except OSError:
            continue
        items.append(
            ProjectFileItem(
                source=source,  # type: ignore[arg-type]
                path=rel,
                name=path.name,
                size=stat.st_size,
                modified_at=_iso_mtime(path),
                category=_category(source, rel),  # type: ignore[arg-type]
            )
        )
    return items


@router.get("/projects/{project_id}/files", response_model=ProjectFilesResponse)
def list_project_files(project_id: str):
    validate_project_id(project_id)
    with get_conn() as conn:
        get_project_or_404(conn, project_id)

    files = [
        *_iter_files(_PROJECT_FILES_ROOT / project_id, "project"),
        *_iter_files(_ATTACHMENTS_ROOT / project_id, "attachment"),
    ]
    files.sort(key=lambda item: (item.category, item.source, item.path))
    return ProjectFilesResponse(project_id=project_id, files=files)


@router.get("/projects/{project_id}/files/download")
def download_project_file(
    project_id: str,
    source: str = Query(..., pattern="^(project|attachment)$"),
    path: str = Query(..., min_length=1),
):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)

    target = _resolve_project_file(project_id, source, path)
    download_size_guard(target)
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    disposition = force_attachment_disposition(media_type)
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name,
        # The FileResponse ``content_disposition_type`` controls the
        # disposition header that ships with the response. We override
        # it to ``attachment`` for any HTML/SVG payload to neutralize
        # a stored-XSS pivot that would otherwise render attacker-
        # controlled HTML inside the SPA.
        content_disposition_type=disposition,
    )
