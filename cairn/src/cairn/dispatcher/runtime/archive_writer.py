from __future__ import annotations

import io
import tarfile
from pathlib import Path, PurePosixPath


def text_file_archive(path: str, content: str) -> tuple[str, bytes]:
    target = PurePosixPath(path)
    if not target.is_absolute() or target.name in ("", ".", ".."):
        raise ValueError(f"container file path must be absolute: {path}")
    parts = target.parts[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"invalid container file path: {path}")
    archive_parts: tuple[str, ...]
    if len(parts) == 1:
        archive_path = "/"
        archive_parts = parts
    else:
        archive_path = f"/{parts[0]}"
        archive_parts = parts[1:]

    payload = content.encode("utf-8")
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        parent = ""
        for part in archive_parts[:-1]:
            parent = f"{parent}/{part}" if parent else part
            info = tarfile.TarInfo(parent)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)

        file_name = "/".join(archive_parts)
        info = tarfile.TarInfo(file_name)
        info.size = len(payload)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(payload))
    return archive_path, stream.getvalue()


def directory_archive(path: str, source: Path) -> tuple[str, bytes]:
    target = PurePosixPath(path)
    if not target.is_absolute() or target.name in ("", ".", ".."):
        raise ValueError(f"container directory path must be absolute: {path}")
    parts = target.parts[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"invalid container directory path: {path}")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f"source must be a directory: {source}")
    archive_path = f"/{parts[0]}" if len(parts) > 1 else "/"
    prefix = "/".join(parts[1:]) if len(parts) > 1 else parts[0]

    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        root_info = tarfile.TarInfo(prefix)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        archive.addfile(root_info)
        for item in sorted(source.rglob("*")):
            relative = item.relative_to(source)
            if any(part in ("", ".", "..") for part in relative.parts):
                continue
            arcname = f"{prefix}/{relative}"
            if item.is_dir():
                info = tarfile.TarInfo(arcname)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
            elif item.is_file():
                archive.add(item, arcname=arcname, recursive=False)
    return archive_path, stream.getvalue()
