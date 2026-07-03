from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cairn.shared.config import ServerResourcePublic


class ServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    enabled: bool = True
    host: str
    port: int = Field(default=22, gt=0, le=65535)
    username: str
    password: str | None = None
    private_key: str | None = None
    description: str = ""

    @field_validator("id", "name", "host", "username", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("password", "private_key")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    enabled: bool | None = None
    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)
    username: str | None = None
    password: str | None = None
    private_key: str | None = None
    description: str | None = None

    @field_validator("name", "host", "username", "description", "password", "private_key")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ServerTestRequest(BaseModel):
    command: str = "true"
    timeout_seconds: int = Field(default=12, gt=0, le=120)


class ServerCommandRequest(BaseModel):
    command: str
    timeout_seconds: int = Field(default=30, gt=0, le=300)

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("command must not be empty")
        return text


class ServerCommandResult(BaseModel):
    ok: bool
    server_id: str
    command: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    message: str = ""


class ServerListResponse(BaseModel):
    servers: list[ServerResourcePublic]
