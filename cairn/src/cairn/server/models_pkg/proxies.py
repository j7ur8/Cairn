from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Re-export shim: ProxyConfig/ProxySummary live in cairn.shared.contracts
# and are surfaced here for importers (application.project_read,
# application.project_creation, routers.proxies). Unused locally by design.
from cairn.shared.contracts import ProxyConfig, ProxySummary  # noqa: F401


class ProxyCreate(BaseModel):
    name: str
    type: Literal["socks5", "http", "https"]
    host: str
    port: int = Field(gt=0, le=65535)
    username: str | None = None
    password: str | None = None

    @field_validator("name", "host")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("username", "password")
    @classmethod
    def validate_auth(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ProxyUpdate(BaseModel):
    name: str | None = None
    type: Literal["socks5", "http", "https"] | None = None
    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)
    username: str | None = None
    password: str | None = None
