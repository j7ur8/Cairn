from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RemoteDnslogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return value.strip()


class RemoteSshConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = ""
    port: int = Field(default=22, gt=0, le=65535)
    username: str = ""
    password: str = ""

    @field_validator("host", "username", "password")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()

    @property
    def is_complete(self) -> bool:
        return bool(self.host and self.username and self.password)


class RemoteSupportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    dnslog: RemoteDnslogConfig = Field(default_factory=RemoteDnslogConfig)
    ssh: RemoteSshConfig = Field(default_factory=RemoteSshConfig)

    @property
    def dnslog_configured(self) -> bool:
        return self.enabled and bool(self.dnslog.url)

    @property
    def ssh_configured(self) -> bool:
        return self.enabled and self.ssh.is_complete

    @property
    def has_available_resource(self) -> bool:
        return self.dnslog_configured or self.ssh_configured

    def environment(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        env: dict[str, str] = {}
        if self.dnslog.url:
            env["CAIRN_DNSLOG_URL"] = self.dnslog.url
        if self.ssh.is_complete:
            env.update(
                {
                    "CAIRN_REMOTE_SSH_HOST": self.ssh.host,
                    "CAIRN_REMOTE_SSH_PORT": str(self.ssh.port),
                    "CAIRN_REMOTE_SSH_USERNAME": self.ssh.username,
                    "CAIRN_REMOTE_SSH_PASSWORD": self.ssh.password,
                }
            )
        if env:
            env["CAIRN_REMOTE_SUPPORT_ENABLED"] = "true"
        return env
