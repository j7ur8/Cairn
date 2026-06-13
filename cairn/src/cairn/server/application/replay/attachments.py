from __future__ import annotations

import shutil
from pathlib import Path


def attachments_root() -> Path:
    from cairn.server.runtime_config import system_config

    return Path(system_config().paths.resolved_attachments_root)


def copy_project_attachments(source_project_id: str, replay_project_id: str) -> Path | None:
    source = attachments_root() / source_project_id
    if not source.exists() or not source.is_dir():
        return None
    target = attachments_root() / replay_project_id
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def rewrite_attachment_refs(text: str, source_project_id: str, replay_project_id: str) -> str:
    from cairn.server.runtime_config import system_config

    worker_root = system_config().paths.worker_attachments_root.rstrip("/")
    return text.replace(
        f"{worker_root}/{source_project_id}",
        f"{worker_root}/{replay_project_id}",
    )
