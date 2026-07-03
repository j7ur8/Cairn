from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from cairn.server.config.files import resources_yaml_path
from cairn.shared.config import ServerResourceConfig

SSH_CERT_ROOT = Path("capabilities/ssh_certs")


class ServerCertificateStore:
    def __init__(self, root: Path | None = None):
        self.root = root or (resources_yaml_path().parent / SSH_CERT_ROOT)

    def save_upload(self, server_id: str, certificate: UploadFile) -> tuple[str, Path]:
        filename = _safe_filename(certificate.filename or "certificate.pem")
        relative = Path("servers") / server_id / f"{uuid.uuid4().hex}_{filename}"
        target = self._resolve_relative(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            certificate.file.seek(0)
            with target.open("wb") as handle:
                shutil.copyfileobj(certificate.file, handle)
            os.chmod(target, 0o600)
        except Exception:
            unlink_quietly(target)
            raise
        return relative.as_posix(), target

    def resolve(self, server: ServerResourceConfig) -> Path:
        if not server.cert_path:
            raise HTTPException(400, f"server {server.id} certificate auth requires cert_path")
        return self._resolve_relative(server.cert_path)

    def delete_cert_path(self, cert_path: str | None) -> None:
        if not cert_path:
            return
        unlink_quietly(self._resolve_relative(cert_path))

    def cleanup_server_dir(self, server_id: str) -> None:
        server_root = self._resolve_relative("servers")
        server_dir = (server_root / server_id).resolve(strict=False)
        if not server_dir.is_relative_to(server_root):
            raise HTTPException(400, "server certificate directory must stay inside capabilities/ssh_certs/servers")
        if server_dir.exists():
            shutil.rmtree(server_dir)

    def _resolve_relative(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve(strict=False)
        root = self.root.resolve(strict=False)
        if not path.is_relative_to(root):
            raise HTTPException(400, "cert_path must stay inside capabilities/ssh_certs")
        return path


def _safe_filename(filename: str) -> str:
    name = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return safe or "certificate.pem"


def unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
