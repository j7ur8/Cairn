from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from cairn.server.config.files import load_resources_data, resources_yaml_path, save_resources_data, utcnow
from cairn.server.schemas.servers import ServerCommandRequest, ServerCommandResult, ServerCreate, ServerUpdate
from cairn.shared.config import ServerAuthMethod, ServerResourceConfig, ServerResourcePublic

SSH_CERT_ROOT = Path("capabilities/ssh_certs")


def list_yaml_servers() -> list[ServerResourcePublic]:
    return [_public(server) for server in _server_configs()]


def get_yaml_server(server_id: str) -> ServerResourceConfig:
    for server in _server_configs():
        if server.id == server_id:
            return server
    raise HTTPException(404, f"server not found: {server_id}")


def create_yaml_server(body: ServerCreate, *, certificate: UploadFile | None = None) -> ServerResourcePublic:
    data = load_resources_data()
    entries = _servers(data)
    if any(isinstance(item, dict) and item.get("id") == body.id for item in entries):
        raise HTTPException(409, f"server already exists: {body.id}")
    saved_cert: Path | None = None
    payload = body.model_dump(exclude_none=True)
    if certificate is not None and certificate.filename:
        cert_path, saved_cert = _save_certificate_upload(body.id, certificate)
        payload["cert_path"] = cert_path
    payload.setdefault("last_test_ok", None)
    payload.setdefault("last_test_at", None)
    payload.setdefault("last_test_message", "")
    try:
        server = ServerResourceConfig.model_validate(payload)
        entries.append(server.model_dump(exclude_none=True))
        save_resources_data(data)
        return _public(server)
    except Exception:
        if saved_cert is not None:
            _unlink_quietly(saved_cert)
        raise


def update_yaml_server(server_id: str, body: ServerUpdate, *, certificate: UploadFile | None = None) -> ServerResourcePublic:
    data = load_resources_data()
    entries = _servers(data)
    for idx, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("id") != server_id:
            continue
        saved_cert: Path | None = None
        payload = dict(item)
        for key, value in body.model_dump(exclude_unset=True).items():
            if value is not None:
                payload[key] = value
        if certificate is not None and certificate.filename:
            cert_path, saved_cert = _save_certificate_upload(server_id, certificate)
            payload["cert_path"] = cert_path
        payload["id"] = server_id
        try:
            server = ServerResourceConfig.model_validate(payload)
            entries[idx] = server.model_dump(exclude_none=True)
            save_resources_data(data)
            return _public(server)
        except Exception:
            if saved_cert is not None:
                _unlink_quietly(saved_cert)
            raise
    raise HTTPException(404, f"server not found: {server_id}")


def delete_yaml_server(server_id: str) -> None:
    data = load_resources_data()
    entries = _servers(data)
    for idx, item in enumerate(entries):
        if isinstance(item, dict) and item.get("id") == server_id:
            entries.pop(idx)
            save_resources_data(data)
            return
    raise HTTPException(404, f"server not found: {server_id}")


def test_yaml_server(server_id: str, *, command: str = "true", timeout_seconds: int = 12) -> ServerCommandResult:
    result = run_yaml_server_command(server_id, ServerCommandRequest(command=command, timeout_seconds=timeout_seconds))
    _record_test_result(server_id, result.ok, result.message or result.stderr or result.stdout)
    return result


def inspect_yaml_server_listening_ports(server_id: str) -> ServerCommandResult:
    command = "ss -lntup 2>/dev/null || netstat -lntup 2>/dev/null || lsof -nP -iTCP -sTCP:LISTEN"
    return run_yaml_server_command(server_id, ServerCommandRequest(command=command, timeout_seconds=30))


def run_yaml_server_command(server_id: str, request: ServerCommandRequest) -> ServerCommandResult:
    server = get_yaml_server(server_id)
    failures: list[str] = []
    last_exit_code: int | None = None
    last_stdout = ""
    last_stderr = ""
    for method in server.auth_order:
        cleanup = lambda: None
        try:
            argv, cleanup = _ssh_argv(server, request.command, method)
            completed = subprocess.run(
                argv,
                text=True,
                capture_output=True,
                timeout=request.timeout_seconds,
                check=False,
            )
            if completed.returncode == 0:
                return ServerCommandResult(
                    ok=True,
                    server_id=server_id,
                    command=request.command,
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    message=f"ok via {method}",
                )
            last_exit_code = completed.returncode
            last_stdout = completed.stdout
            last_stderr = completed.stderr
            failures.append(f"{method}: ssh command failed with exit code {completed.returncode}")
        except subprocess.TimeoutExpired as exc:
            last_stdout = exc.stdout or ""
            last_stderr = exc.stderr or ""
            failures.append(f"{method}: ssh command timed out after {request.timeout_seconds}s")
        except HTTPException as exc:
            failures.append(f"{method}: {exc.detail}")
        except FileNotFoundError as exc:
            failures.append(f"{method}: {exc}")
        finally:
            cleanup()
    return ServerCommandResult(
        ok=False,
        server_id=server_id,
        command=request.command,
        exit_code=last_exit_code,
        stdout=last_stdout,
        stderr=last_stderr,
        message="; ".join(failures) or "no auth methods available",
    )


def _server_configs() -> list[ServerResourceConfig]:
    data = load_resources_data()
    return [ServerResourceConfig.model_validate(item) for item in _servers(data)]


def _servers(data: dict[str, Any]) -> list[dict[str, Any]]:
    entries = data.setdefault("servers", [])
    if not isinstance(entries, list):
        raise HTTPException(500, "config.resources.yaml servers must be a list")
    return entries


def _public(server: ServerResourceConfig) -> ServerResourcePublic:
    return ServerResourcePublic(
        id=server.id,
        name=server.name,
        enabled=server.enabled,
        host=server.host,
        port=server.port,
        username=server.username,
        auth_order=list(server.auth_order),
        has_password=bool(server.password),
        has_private_key=bool(server.private_key),
        cert_path=server.cert_path,
        description=server.description,
        last_test_ok=server.last_test_ok,
        last_test_at=server.last_test_at,
        last_test_message=server.last_test_message,
    )


def _record_test_result(server_id: str, ok: bool, message: str) -> None:
    data = load_resources_data()
    entries = _servers(data)
    for item in entries:
        if isinstance(item, dict) and item.get("id") == server_id:
            item["last_test_ok"] = ok
            item["last_test_at"] = utcnow()
            item["last_test_message"] = message[:1000]
            save_resources_data(data, reload_dispatcher=False)
            return


def _ssh_argv(server: ServerResourceConfig, command: str, method: ServerAuthMethod) -> tuple[list[str], Any]:
    cleanup_callbacks = []
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(server.port),
    ]
    if method == "password":
        if not server.password:
            raise HTTPException(400, f"server {server.id} password auth requires password")
        if not shutil.which("sshpass"):
            raise HTTPException(400, "password auth testing requires sshpass on this host")
        fd, password_path = tempfile.mkstemp(prefix="cairn-ssh-password-", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(server.password)
            if not server.password.endswith("\n"):
                handle.write("\n")
        os.chmod(password_path, 0o600)

        def cleanup_password() -> None:
            try:
                os.unlink(password_path)
            except OSError:
                pass

        cleanup_callbacks.append(cleanup_password)
        argv[2] = "BatchMode=no"
        argv.extend(["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"])
        argv = ["sshpass", "-f", password_path, *argv]
    if method == "private_key":
        if not server.private_key:
            raise HTTPException(400, f"server {server.id} private_key auth requires private_key")
        fd, key_path = tempfile.mkstemp(prefix="cairn-ssh-key-", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(server.private_key)
            if not server.private_key.endswith("\n"):
                handle.write("\n")
        os.chmod(key_path, 0o600)

        def cleanup_key() -> None:
            try:
                os.unlink(key_path)
            except OSError:
                pass

        cleanup_callbacks.append(cleanup_key)
        argv.extend(["-i", key_path])
    if method == "certificate":
        argv.extend(["-i", str(resolve_cert_path(server))])
    argv.extend([f"{server.username}@{server.host}", command])

    def cleanup() -> None:
        for callback in cleanup_callbacks:
            callback()

    return argv, cleanup


def _save_certificate_upload(server_id: str, certificate: UploadFile) -> tuple[str, Path]:
    filename = _safe_filename(certificate.filename or "certificate.pem")
    relative = Path("servers") / server_id / f"{uuid.uuid4().hex}_{filename}"
    base = resources_yaml_path().parent / SSH_CERT_ROOT
    target = (base / relative).resolve(strict=False)
    base_resolved = base.resolve(strict=False)
    if not target.is_relative_to(base_resolved):
        raise HTTPException(400, "certificate path must stay inside capabilities/ssh_certs")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        certificate.file.seek(0)
        with target.open("wb") as handle:
            shutil.copyfileobj(certificate.file, handle)
        os.chmod(target, 0o600)
    except Exception:
        _unlink_quietly(target)
        raise
    return relative.as_posix(), target


def _safe_filename(filename: str) -> str:
    name = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return safe or "certificate.pem"


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def resolve_cert_path(server: ServerResourceConfig) -> Path:
    if not server.cert_path:
        raise HTTPException(400, f"server {server.id} certificate auth requires cert_path")
    base = resources_yaml_path().parent / SSH_CERT_ROOT
    path = (base / server.cert_path).resolve(strict=False)
    base_resolved = base.resolve(strict=False)
    if not path.is_relative_to(base_resolved):
        raise HTTPException(400, "cert_path must stay inside capabilities/ssh_certs")
    return path
