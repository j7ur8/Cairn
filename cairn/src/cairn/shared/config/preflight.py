from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jwt

from cairn.shared.config.loader import ConfigError, load_dispatch_config
from cairn.shared.config.root import DispatchConfig

MIN_JWT_SECRET_LENGTH = 32
PROJECT_ID_PLACEHOLDER = "preflight-project"
PROJECT_FILES_MOUNT_NAME = "project-files"
PROJECT_WORKSPACE_PATH = "/home/kali/workspace"


@dataclass(slots=True)
class PreflightResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked": self.checked,
        }


def check_dispatch_config(path: Path, *, strict: bool = False) -> PreflightResult:
    """Run startup-oriented checks without connecting to the database or mutating files."""
    result = PreflightResult()
    config_path = path.expanduser()
    try:
        config = load_dispatch_config(config_path)
    except ConfigError as exc:
        result.errors.append(str(exc))
        result.checked.append("dispatch_config")
        return result

    result.checked.append("dispatch_config")
    _check_auth(config, result)
    _check_paths(config, result)
    _check_bind_mounts(config, result)
    _check_project_files_bind_mount_alignment(config, result)
    _check_container_security(config, result)
    _check_worker_image(config, result, strict=strict)
    return result


def _check_auth(config: DispatchConfig, result: PreflightResult) -> None:
    secret = config.server.auth.jwt_secret.strip()
    token = config.server.auth.dispatcher_api_token.strip()

    result.checked.append("auth.jwt_secret")
    if _looks_like_placeholder(secret):
        result.errors.append("server.auth.jwt_secret is still a placeholder value")
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        result.errors.append(
            f"server.auth.jwt_secret must be at least {MIN_JWT_SECRET_LENGTH} characters"
        )

    result.checked.append("auth.dispatcher_api_token")
    if not token:
        result.errors.append("server.auth.dispatcher_api_token must not be empty")
        return
    if _looks_like_placeholder(token):
        result.errors.append("server.auth.dispatcher_api_token is still a placeholder value")
        return

    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        result.errors.append("server.auth.dispatcher_api_token is expired")
        return
    except jwt.InvalidTokenError as exc:
        result.errors.append(f"server.auth.dispatcher_api_token is not valid for jwt_secret: {exc}")
        return

    if claims.get("role") != "service":
        result.errors.append("server.auth.dispatcher_api_token must include role=service")
    if not claims.get("sub"):
        result.errors.append("server.auth.dispatcher_api_token must include a subject")


def _check_paths(config: DispatchConfig, result: PreflightResult) -> None:
    result.checked.append("server.paths")
    for label, raw in (
        ("server.paths.datas_root", config.server.paths.datas_root),
        ("server.paths.attachments_root", config.server.paths.resolved_attachments_root),
        ("server.paths.project_files_root", config.server.paths.resolved_project_files_root),
    ):
        _check_host_path(label, Path(raw).expanduser(), result, allow_missing=True)


def _check_bind_mounts(config: DispatchConfig, result: PreflightResult) -> None:
    result.checked.append("worker_runtime.container.bind_mounts")
    for mount in config.container.bind_mounts:
        label = f"worker_runtime.container.bind_mounts[{mount.name or mount.container_path}].host_path"
        rendered = mount.host_path.replace("{project_id}", PROJECT_ID_PLACEHOLDER)
        path = Path(rendered).expanduser()
        if "{project_id}" in mount.host_path:
            _check_host_path(label, path.parent, result, allow_missing=True)
        else:
            _check_host_path(label, path, result, allow_missing=True)


def _check_project_files_bind_mount_alignment(config: DispatchConfig, result: PreflightResult) -> None:
    result.checked.append("worker_runtime.container.bind_mounts[project-files].alignment")
    mounts = [mount for mount in config.container.bind_mounts if mount.name == PROJECT_FILES_MOUNT_NAME]
    if not mounts:
        result.errors.append(
            "worker_runtime.container.bind_mounts must include writable project-files mount "
            f"at {PROJECT_WORKSPACE_PATH}"
        )
        return
    mount = mounts[0]
    if mount.read_only:
        result.errors.append("worker_runtime.container.bind_mounts[project-files] must be read_write")
    if mount.container_path != PROJECT_WORKSPACE_PATH:
        result.errors.append(
            "worker_runtime.container.bind_mounts[project-files].container_path must be "
            f"{PROJECT_WORKSPACE_PATH}"
        )

    expected = Path(config.server.paths.resolved_project_files_root).expanduser() / PROJECT_ID_PLACEHOLDER
    actual = Path(mount.host_path.replace("{project_id}", PROJECT_ID_PLACEHOLDER)).expanduser()
    expected_resolved = expected.resolve(strict=False)
    actual_resolved = actual.resolve(strict=False)
    if actual_resolved != expected_resolved:
        result.errors.append(
            "worker_runtime.container.bind_mounts[project-files].host_path must align with "
            "server.paths.project_files_root; "
            f"expected {expected_resolved}, got {actual_resolved}"
        )


def _check_container_security(config: DispatchConfig, result: PreflightResult) -> None:
    result.checked.append("worker_runtime.container.security")
    user = (config.container.user or "").strip()
    if not user:
        result.warnings.append(
            "worker_runtime.container.user is not set; worker containers will "
            "run as root (the image default). Recommend setting an explicit "
            "non-root user."
        )
    elif user == "root" or user == "0":
        result.warnings.append(
            "worker_runtime.container.user is 'root'; worker containers will "
            "run with full root privileges. Recommend a non-root user."
        )


def _check_worker_image(config: DispatchConfig, result: PreflightResult, *, strict: bool) -> None:
    result.checked.append("worker_runtime.container.image")
    image = config.container.image.strip()
    if not _looks_like_image_ref(image):
        result.errors.append(f"worker_runtime.container.image is not a valid image reference: {image!r}")
        return
    if _uses_latest_tag(image):
        result.errors.append("worker_runtime.container.image must not use the mutable latest tag")
    if "@" not in image:
        result.warnings.append("worker_runtime.container.image is not pinned by digest; production deployments should use image@sha256:...")

    try:
        import docker
        from docker.errors import DockerException, ImageNotFound
    except ImportError:
        message = "Docker SDK is unavailable; worker image existence was not checked"
        (result.errors if strict else result.warnings).append(message)
        return

    try:
        client = docker.from_env()
        try:
            client.images.get(image)
        finally:
            client.close()
    except ImageNotFound:
        message = f"worker image is not present locally: {image}"
        (result.errors if strict else result.warnings).append(message)
    except DockerException as exc:
        message = f"Docker daemon unavailable; worker image existence was not checked: {exc}"
        (result.errors if strict else result.warnings).append(message)


def _check_host_path(label: str, path: Path, result: PreflightResult, *, allow_missing: bool) -> None:
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        result.errors.append(f"{label} cannot be resolved: {exc}")
        return
    if "\x00" in str(resolved):
        result.errors.append(f"{label} contains a NUL byte")
        return
    if resolved.exists():
        return
    if allow_missing:
        result.warnings.append(f"{label} does not exist yet and may need to be created: {resolved}")
    else:
        result.errors.append(f"{label} does not exist: {resolved}")


def _looks_like_placeholder(value: str) -> bool:
    text = value.strip().lower()
    return (
        not text
        or text.startswith("change-me")
        or text.startswith("test-")
        or text in {"changeme", "replace-me", "replace_me"}
        or "do-not-use" in text
        or "example" in text
        or "replace-me" in text
    )


_IMAGE_REF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/@+-]{0,254}$")


def _looks_like_image_ref(value: str) -> bool:
    if not value or any(ch.isspace() for ch in value):
        return False
    return _IMAGE_REF_RE.match(value) is not None


def _uses_latest_tag(value: str) -> bool:
    image = value.split("@", 1)[0]
    last_segment = image.rsplit("/", 1)[-1]
    return ":" not in last_segment or last_segment.endswith(":latest")
