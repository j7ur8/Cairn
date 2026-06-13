from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from fastapi import HTTPException

from cairn.server.domain.projects import require_project, require_project_hint_writable
from cairn.server.domain.time import utcnow
from cairn.server.models_pkg import CreateHintRequest
from cairn.server.models_pkg.projects import (
    AttachmentUpload,
    AttachmentUploadResponse,
    ProjectFileItem,
    ProjectFilesResponse,
)
from cairn.server.repositories.ids import IdRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.security.paths import (
    download_size_guard,
    force_attachment_disposition,
    safe_resolve_within,
    validate_project_id,
    validate_relative_path,
)
from cairn.shared.contracts import Hint

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(frozen=True)
class IncomingAttachment:
    filename: str | None
    file: BinaryIO


@dataclass(frozen=True)
class DownloadTarget:
    path: Path
    media_type: str
    filename: str
    content_disposition_type: str


def host_attachment_root() -> Path:
    from cairn.server.runtime_config import system_config

    return Path(system_config().paths.resolved_attachments_root)


def worker_attachment_root() -> str:
    from cairn.server.runtime_config import system_config

    return system_config().paths.worker_attachments_root.rstrip("/")


def project_files_root() -> Path:
    from cairn.server.runtime_config import system_config

    return Path(system_config().paths.resolved_project_files_root)


def create_hint(conn: Any, project_id: str, body: CreateHintRequest) -> Hint:
    projects = ProjectRepository(conn)
    require_project_hint_writable(projects.get(project_id))

    now = utcnow()
    hint_id = IdRepository(conn).next_hint_id(project_id)
    projects.insert_hint(project_id, hint_id, body.content, body.creator, now)
    return Hint(id=hint_id, content=body.content, creator=body.creator, created_at=now)


def upload_project_attachments(
    conn: Any,
    project_id: str,
    *,
    uploaded: list[tuple[str, str, int, str, str]],
    creator: str,
) -> AttachmentUploadResponse:
    projects = ProjectRepository(conn)
    require_project_hint_writable(projects.get(project_id))
    now = utcnow()
    ids = IdRepository(conn)
    attachments: list[AttachmentUpload] = []
    for original_filename, stored_filename, size, worker_path, hint in uploaded:
        hint_id = ids.next_hint_id(project_id)
        projects.insert_hint(project_id, hint_id, hint, creator, now)
        attachments.append(
            AttachmentUpload(
                original_filename=original_filename,
                stored_filename=stored_filename,
                size=size,
                path=worker_path,
                hint_id=hint_id,
                hint=hint,
            )
        )
    return AttachmentUploadResponse(project_id=project_id, attachments=attachments)


def verify_attachments_writable(conn: Any, project_id: str) -> None:
    require_project_hint_writable(ProjectRepository(conn).get(project_id))


def write_attachment_files(
    project_id: str,
    files: list[IncomingAttachment],
    descriptions: list[str] | None,
) -> tuple[list[tuple[str, str, int, str, str]], list[Path]]:
    if not files:
        raise HTTPException(400, "No files uploaded")
    validate_project_id(project_id)

    project_dir = host_attachment_root() / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    uploaded: list[tuple[str, str, int, str, str]] = []
    written_paths: list[Path] = []
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
        worker_path = f"{worker_attachment_root()}/{project_id}/{target.name}"
        description = descriptions[idx] if descriptions and idx < len(descriptions) else ""
        hint = _attachment_hint(description, worker_path)
        uploaded.append((original_filename, target.name, size, worker_path, hint))
    return uploaded, written_paths


def cleanup_paths(paths: list[Path]) -> None:
    for target in paths:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass


def list_project_files(conn: Any, project_id: str) -> ProjectFilesResponse:
    validate_project_id(project_id)
    require_project(ProjectRepository(conn).get(project_id))

    files = [
        *_iter_files(project_files_root() / project_id, "project"),
        *_iter_files(host_attachment_root() / project_id, "attachment"),
    ]
    files.sort(key=lambda item: (item.category, item.source, item.path))
    return ProjectFilesResponse(project_id=project_id, files=files)


def download_project_file(conn: Any, project_id: str, source: str, rel_path: str) -> DownloadTarget:
    require_project(ProjectRepository(conn).get(project_id))
    target = _resolve_project_file(project_id, source, rel_path)
    download_size_guard(target)
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return DownloadTarget(
        path=target,
        media_type=media_type,
        filename=target.name,
        content_disposition_type=force_attachment_disposition(media_type),
    )


def _safe_filename(filename: str) -> str:
    name = Path(filename or "attachment").name.strip().replace("\x00", "")
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = name.strip(" .")
    if not name:
        name = "attachment"
    return name[:180]


def _dedupe_path(project_dir: Path, filename: str) -> Path:
    # Refuse any path component that tries to escape the project directory.
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


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_project_file(project_id: str, source: str, rel_path: str) -> Path:
    if source == "project":
        root = project_files_root() / project_id
    elif source == "attachment":
        root = host_attachment_root() / project_id
    else:
        raise HTTPException(400, "source must be project or attachment")

    validate_project_id(project_id)
    rel = validate_relative_path(rel_path)
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
