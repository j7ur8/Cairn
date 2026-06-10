from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from cairn.server import db
from cairn.server.models_pkg.projects import AttachmentUpload, AttachmentUploadResponse
from cairn.server.repositories import sql
from cairn.server.security.paths import validate_project_id
from cairn.server.services import check_project_hint_writable, next_hint_id, utcnow

router = APIRouter(tags=["attachments"])

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def _host_attachment_root() -> Path:
    from cairn.server.runtime_config import system_config
    return Path(system_config().paths.resolved_attachments_root)


def _worker_attachment_root() -> str:
    from cairn.server.runtime_config import system_config
    return system_config().paths.worker_attachments_root.rstrip("/")


def _safe_filename(filename: str) -> str:
    name = Path(filename or "attachment").name.strip().replace("\x00", "")
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = name.strip(" .")
    if not name:
        name = "attachment"
    return name[:180]


def _dedupe_path(project_dir: Path, filename: str) -> Path:
    # Refuse any path component that tries to escape the project
    # directory, even though _safe_filename should have stripped
    # slashes already. This is the TOCTOU safety net.
    safe = filename.replace("/", "_").replace("\\", "_")
    candidate = (project_dir / safe).resolve(strict=False)
    if not str(candidate).startswith(str(project_dir.resolve(strict=False))):
        raise HTTPException(400, "invalid filename")
    if not candidate.exists():
        return candidate
    stem = candidate.stem or "attachment"
    suffix = candidate.suffix
    index = 1
    while True:
        candidate = project_dir / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _attachment_hint(description: str | None, worker_path: str) -> str:
    label = (description or "附件").strip() or "附件"
    return f"{label}为 worker 容器内文件：{worker_path}"


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
    validate_project_id(project_id)

    creator = creator.strip() or "Human"
    with db.session_scope() as conn:
        check_project_hint_writable(conn, project_id)

    project_dir = _host_attachment_root() / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    uploaded: list[tuple[str, str, int, str, str]] = []
    written_paths: list[Path] = []
    try:
        for idx, upload in enumerate(files):
            original_filename = upload.filename or "attachment"
            stored_filename = _safe_filename(original_filename)
            target = _dedupe_path(project_dir, stored_filename)
            written_paths.append(target)
            size = 0
            with target.open("wb") as out:
                while chunk := upload.file.read(1024 * 1024):
                    size += len(chunk)
                    out.write(chunk)
            worker_path = f"{_worker_attachment_root()}/{project_id}/{target.name}"
            description = descriptions[idx] if descriptions and idx < len(descriptions) else ""
            hint = _attachment_hint(description, worker_path)
            uploaded.append((original_filename, target.name, size, worker_path, hint))
    except Exception:
        for target in written_paths:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    finally:
        for upload in files:
            upload.file.close()

    attachments: list[AttachmentUpload] = []
    try:
        with db.session_scope() as conn:
            check_project_hint_writable(conn, project_id)
            now = utcnow()
            for original_filename, stored_filename, size, worker_path, hint in uploaded:
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
                        "content": hint,
                        "creator": creator,
                        "created_at": now,
                    },
                )
                attachments.append(
                    AttachmentUpload(
                        original_filename=original_filename,
                        stored_filename=stored_filename,
                        size=size,
                        path=worker_path,
                        hint_id=hid,
                        hint=hint,
                    )
                )
    except Exception:
        for target in written_paths:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
        raise

    return AttachmentUploadResponse(project_id=project_id, attachments=attachments)
