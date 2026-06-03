from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from cairn.server.db import get_conn
from cairn.server.models import ProjectFileItem, ProjectFilesResponse
from cairn.server.services import get_project_or_404

router = APIRouter(tags=["files"])

_REPO_ROOT = Path(__file__).resolve().parents[5]
_PROJECT_FILES_ROOT = Path(os.environ.get("CAIRN_PROJECT_FILES_ROOT", str(_REPO_ROOT / "datas" / "project-files")))
_ATTACHMENTS_ROOT = Path(os.environ.get("CAIRN_ATTACHMENTS_ROOT", str(_REPO_ROOT / "datas" / "attachments")))


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_relative_path(value: str) -> PurePosixPath:
    text = (value or "").strip()
    if not text:
        raise HTTPException(400, "path must not be empty")
    rel = PurePosixPath(text)
    if not rel.parts or rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise HTTPException(400, "invalid path")
    return rel


def _resolve_project_file(project_id: str, source: str, rel_path: str) -> Path:
    if source == "project":
        root = _PROJECT_FILES_ROOT / project_id
    elif source == "attachment":
        root = _ATTACHMENTS_ROOT / project_id
    else:
        raise HTTPException(400, "source must be project or attachment")

    rel = _safe_relative_path(rel_path)
    root_resolved = root.resolve(strict=False)
    target = (root / Path(*rel.parts)).resolve(strict=False)
    if target != root_resolved and root_resolved not in target.parents:
        raise HTTPException(400, "invalid path")
    if not target.exists() or not target.is_file():
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
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type, filename=target.name)
