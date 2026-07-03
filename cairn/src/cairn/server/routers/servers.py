from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from cairn.server.config.servers import (
    create_yaml_server,
    delete_yaml_server,
    inspect_yaml_server_listening_ports,
    list_yaml_servers,
    run_yaml_server_command,
    test_yaml_server,
    update_yaml_server,
)
from cairn.server.schemas.servers import ServerCommandRequest, ServerCommandResult, ServerCreate, ServerUpdate
from cairn.server.security.deps import current_active_superuser
from cairn.shared.config import ServerResourcePublic

router = APIRouter(tags=["servers"])


@router.get("/servers", response_model=list[ServerResourcePublic])
def list_servers():
    return list_yaml_servers()


def _parse_payload(payload: str) -> dict:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid server payload JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "server payload must be a JSON object")
    return data


@router.post("/servers/add", response_model=ServerResourcePublic, status_code=201)
def create_server(
    payload: Annotated[str, Form()],
    certificate: Annotated[UploadFile | None, File()] = None,
    _superuser=Depends(current_active_superuser),
):
    try:
        body = ServerCreate.model_validate(_parse_payload(payload))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from exc
    return create_yaml_server(body, certificate=certificate)


@router.put("/servers/{server_id}", response_model=ServerResourcePublic)
def update_server(
    server_id: str,
    payload: Annotated[str, Form()],
    certificate: Annotated[UploadFile | None, File()] = None,
    _superuser=Depends(current_active_superuser),
):
    try:
        body = ServerUpdate.model_validate(_parse_payload(payload))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from exc
    return update_yaml_server(server_id, body, certificate=certificate)


@router.delete("/servers/{server_id}", status_code=204)
def delete_server(server_id: str, _superuser=Depends(current_active_superuser)):
    delete_yaml_server(server_id)
    return None


@router.post("/servers/{server_id}/test", response_model=ServerCommandResult)
def test_server(server_id: str, body: ServerCommandRequest, _superuser=Depends(current_active_superuser)):
    return test_yaml_server(server_id, command=body.command, timeout_seconds=body.timeout_seconds)


@router.post("/servers/{server_id}/run-command", response_model=ServerCommandResult)
def run_server_command(server_id: str, body: ServerCommandRequest):
    return run_yaml_server_command(server_id, body)


@router.post("/servers/{server_id}/inspect-listening-ports", response_model=ServerCommandResult)
def inspect_server_ports(server_id: str):
    return inspect_yaml_server_listening_ports(server_id)
