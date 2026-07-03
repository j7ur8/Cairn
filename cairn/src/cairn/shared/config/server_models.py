from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ServerAuthType = Literal["password", "private_key", "certificate"]
ServerAuthMethod = ServerAuthType
SERVER_AUTH_ORDER: tuple[ServerAuthMethod, ...] = ("private_key", "certificate", "password")


class ServerResourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    enabled: bool = True
    host: str
    port: int = Field(default=22, gt=0, le=65535)
    username: str
    auth_order: list[ServerAuthMethod] = Field(default_factory=list)
    password: str | None = None
    private_key: str | None = None
    cert_path: str | None = None
    description: str = ""
    last_test_ok: bool | None = None
    last_test_at: str | None = None
    last_test_message: str = ""

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("id must not be empty")
        if any(ch.isspace() for ch in text) or "/" in text or "\\" in text:
            raise ValueError("id must not contain whitespace, '/', or '\\'")
        return text

    @field_validator("name", "host", "username", "description", "last_test_message")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("password", "private_key", "cert_path", "last_test_at")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("cert_path")
    @classmethod
    def validate_cert_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\x00" in value:
            raise ValueError("cert_path must not contain NUL bytes")
        path = PurePosixPath(value)
        if path.is_absolute():
            raise ValueError("cert_path must be relative to capabilities/ssh_certs")
        if any(part in ("", ".", "..") for part in path.parts):
            raise ValueError("cert_path must not contain empty, '.', or '..' segments")
        return str(path)

    @model_validator(mode="after")
    def validate_auth_material(self) -> ServerResourceConfig:
        available = {
            "password": bool(self.password),
            "private_key": bool(self.private_key),
            "certificate": bool(self.cert_path),
        }
        if not any(available.values()):
            raise ValueError("server requires at least one auth material: password, private_key, or cert_path")
        self.auth_order = [method for method in SERVER_AUTH_ORDER if available[method]]
        return self


class ServerResourcePublic(BaseModel):
    id: str
    name: str
    enabled: bool = True
    host: str
    port: int
    username: str
    auth_order: list[ServerAuthMethod]
    has_password: bool = False
    has_private_key: bool = False
    cert_path: str | None = None
    description: str = ""
    last_test_ok: bool | None = None
    last_test_at: str | None = None
    last_test_message: str = ""
