from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from cairn.server.config.server_certificates import ServerCertificateStore, unlink_quietly
from cairn.server.config.server_ssh import ServerSshRunner
from cairn.server.config.server_yaml_repository import ServerYamlRepository, public_server
from cairn.server.schemas.servers import ServerCommandRequest, ServerCommandResult, ServerCreate, ServerUpdate
from cairn.shared.config import ServerResourceConfig, ServerResourcePublic


def _repository() -> ServerYamlRepository:
    return ServerYamlRepository()


def _certificates() -> ServerCertificateStore:
    return ServerCertificateStore()


def list_yaml_servers() -> list[ServerResourcePublic]:
    return [public_server(server) for server in _repository().list()]


def get_yaml_server(server_id: str) -> ServerResourceConfig:
    return _repository().get(server_id)


def create_yaml_server(body: ServerCreate, *, certificate: UploadFile | None = None) -> ServerResourcePublic:
    cert_store = _certificates()
    saved_cert: Path | None = None
    payload = body.model_dump(exclude_none=True)
    if certificate is not None and certificate.filename:
        cert_path, saved_cert = cert_store.save_upload(body.id, certificate)
        payload["cert_path"] = cert_path
    try:
        return public_server(_repository().create(payload))
    except Exception:
        if saved_cert is not None:
            unlink_quietly(saved_cert)
        raise


def update_yaml_server(server_id: str, body: ServerUpdate, *, certificate: UploadFile | None = None) -> ServerResourcePublic:
    repo = _repository()
    cert_store = _certificates()
    payload = repo.raw_payload_for_update(server_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            payload[key] = value
    saved_cert: Path | None = None
    if certificate is not None and certificate.filename:
        cert_path, saved_cert = cert_store.save_upload(server_id, certificate)
        payload["cert_path"] = cert_path
    try:
        server, old_cert_path = repo.update(server_id, payload)
    except Exception:
        if saved_cert is not None:
            unlink_quietly(saved_cert)
        raise
    if saved_cert is not None:
        cert_store.delete_cert_path(old_cert_path)
    return public_server(server)


def delete_yaml_server(server_id: str) -> None:
    _repository().delete(server_id)
    _certificates().cleanup_server_dir(server_id)


def test_yaml_server(server_id: str, *, command: str = "true", timeout_seconds: int = 12) -> ServerCommandResult:
    result = run_yaml_server_command(server_id, ServerCommandRequest(command=command, timeout_seconds=timeout_seconds))
    _repository().record_test_result(server_id, result.ok, result.message or result.stderr or result.stdout)
    return result


def inspect_yaml_server_listening_ports(server_id: str) -> ServerCommandResult:
    command = "ss -lntup 2>/dev/null || netstat -lntup 2>/dev/null || lsof -nP -iTCP -sTCP:LISTEN"
    return run_yaml_server_command(server_id, ServerCommandRequest(command=command, timeout_seconds=30))


def run_yaml_server_command(server_id: str, request: ServerCommandRequest) -> ServerCommandResult:
    return ServerSshRunner(_certificates()).run(get_yaml_server(server_id), request)


def resolve_cert_path(server: ServerResourceConfig) -> Path:
    return _certificates().resolve(server)
