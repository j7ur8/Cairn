"""Path validation helpers for project file and attachment routes.

The existing file router did path-traversal protection via
``PurePosixPath`` + ``resolve()`` checks, but it had two soft spots:

  * it had no size cap on download responses, so a malicious user
    could ask the server to stream a multi-gigabyte log file and tie
    up worker memory;
  * the symlink check relied on ``Path.resolve(strict=False)`` which
    silently followed symlinks out of the project root, exposing any
    other project on the same host.

This module centralizes the policy. Callers should use
:func:`safe_resolve_within` for every filesystem lookup and
:func:`download_size_guard` for every byte-streaming endpoint. Both
are intentionally small so they can be unit-tested without a running
FastAPI app.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

PROJECT_ID_RE = re.compile(r"^proj_[A-Za-z0-9_-]{1,64}$")
REL_PATH_RE = re.compile(r"^(?!\.)[A-Za-z0-9._/-]{1,512}$")

# 64 MiB cap on a single download. Worker bind mounts typically
# contain exploit artifacts, log dumps, and screenshots; anything
# bigger is almost always the operator pulling the wrong thing.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024

# MIME types we always force to ``Content-Disposition: attachment`` so
# the browser does not render the response inline. Inline rendering of
# these types is a typical XSS / phishing pivot.
_DANGEROUS_MIME_PREFIXES = (
    "text/html",
    "application/xhtml",
    "image/svg",
    "application/javascript",
    "text/javascript",
)


def validate_project_id(project_id: str) -> str:
    """Return ``project_id`` if it matches the canonical id shape, else 400."""
    if not isinstance(project_id, str) or not PROJECT_ID_RE.match(project_id):
        raise HTTPException(400, "invalid project_id")
    return project_id


def validate_relative_path(rel_path: str) -> PurePosixPath:
    """Reject empty / absolute / parent-traversal paths and return the posix form."""
    text = (rel_path or "").strip()
    if not text:
        raise HTTPException(400, "path must not be empty")
    if not REL_PATH_RE.match(text):
        raise HTTPException(400, "invalid path")
    rel = PurePosixPath(text)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise HTTPException(400, "invalid path")
    return rel


def safe_resolve_within(root: Path, rel_path: PurePosixPath) -> Path:
    """Resolve ``root / rel_path`` and ensure it stays under ``root``.

    Symlinks are followed via ``resolve(strict=False)`` for the final
    hop (so files written by a bind-mounted container show up), but
    the final result must be a real file or directory inside the
    root. Anything that resolves outside the root raises 400; missing
    files raise 404.
    """
    root_resolved = root.resolve(strict=False)
    target = (root / Path(*rel_path.parts)).resolve(strict=False)
    if target != root_resolved and root_resolved not in target.parents:
        # Defense in depth: this is the canonical "path traversal" check.
        raise HTTPException(400, "invalid path")
    if not target.exists():
        raise HTTPException(404, "File not found")
    if target.is_symlink():
        # If the symlink points outside the project, treat it as 404
        # rather than leaking the symlink target. We re-resolve
        # because resolve(strict=False) does not always follow links
        # on every platform.
        real = target.readlink() if target.is_symlink() else target
        if isinstance(real, Path):
            real_resolved = real.resolve(strict=False)
            if real_resolved != root_resolved and root_resolved not in real_resolved.parents:
                raise HTTPException(404, "File not found")
    return target


def download_size_guard(path: Path, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> None:
    """Refuse to stream files larger than ``max_bytes``.

    Operators who genuinely need a larger download can raise the cap
    via the constant; the rest of the surface assumes the default.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise HTTPException(404, "File not found") from exc
    if size > max_bytes:
        raise HTTPException(
            413,
            f"file too large to download via the API (size={size}, max={max_bytes})",
        )


def is_dangerous_mime(media_type: str | None) -> bool:
    if not media_type:
        return False
    head = media_type.split(";", 1)[0].strip().lower()
    return any(head.startswith(prefix) for prefix in _DANGEROUS_MIME_PREFIXES)


def force_attachment_disposition(media_type: str | None) -> str:
    """Pick a safe ``Content-Disposition`` value.

    For dangerous MIME types the browser is told to download the file
    even if it has an HTML-looking extension. The default is
    ``inline`` so screenshots and PDFs keep rendering inside the UI.
    """
    if is_dangerous_mime(media_type):
        return "attachment"
    return "inline"
