from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ProxySummary(BaseModel):
    id: str
    name: str
    type: Literal["socks5", "http", "https"]
    host: str
    port: int
    has_auth: bool = False
    created_at: str
    updated_at: str


class ProxyConfig(ProxySummary):
    username: str | None = None
    password: str | None = None
