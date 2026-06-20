from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import cairn.dispatcher.prompts as prompt_package
from cairn.server.config.files import _text_sha256, resources_yaml_path
from cairn.server.execution_config.prompt_snapshot import is_complete_prompt_group_dir, load_prompt_snapshot
from cairn.server.security.deps import current_active_superuser
from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS, PROMPT_REQUIRED_TOKENS_BY_GROUP

router = APIRouter(tags=["prompt-groups"])
DEFAULT_PROMPT_GROUP = "default"


class PromptGroupTemplateUpdate(BaseModel):
    content: str


class PromptGroupDetail(BaseModel):
    prompt_group: str
    prompt_names: list[str]
    prompts: dict[str, str]
    prompt_sha256: dict[str, str]
    prompts_sha256: str


class RolePromptDetail(BaseModel):
    role_names: list[str]
    roles: dict[str, str]
    role_sha256: dict[str, str]


def _prompts_root() -> Path:
    package_paths = list(getattr(prompt_package, "__path__", []))
    if len(package_paths) != 1:
        raise HTTPException(status_code=500, detail="prompt resources are not writable files")
    return Path(package_paths[0]).resolve()


def _roles_root() -> Path:
    return (resources_yaml_path().parent / "capabilities" / "roles").resolve()


def _default_group_dir() -> Path:
    root = _prompts_root()
    group_path = (root / DEFAULT_PROMPT_GROUP).resolve()
    if not group_path.is_relative_to(root) or not group_path.is_dir():
        raise HTTPException(status_code=404, detail="default prompt templates not found")
    return group_path


def _validate_template_name(name: str) -> str:
    parts = name.split("/")
    if not name or name.startswith("/") or "\\" in name or parts != [part for part in parts if part] or ".." in parts:
        raise HTTPException(status_code=400, detail="invalid prompt template name")
    if not name.endswith(".md"):
        raise HTTPException(status_code=400, detail="invalid prompt template name")
    return name


def _template_path(name: str) -> Path:
    name = _validate_template_name(name)
    group_path = _default_group_dir()
    target = (group_path / Path(name)).resolve()
    if not target.is_relative_to(group_path) or not target.is_file():
        raise HTTPException(status_code=404, detail="prompt template not found")
    return target


def _validate_role_prompt_path(path: str) -> str:
    parts = path.split("/")
    if not path or path.startswith("/") or "\\" in path or parts != [part for part in parts if part] or ".." in parts:
        raise HTTPException(status_code=400, detail="invalid role prompt path")
    if not path.endswith(".md"):
        raise HTTPException(status_code=400, detail="invalid role prompt path")
    return path


def _role_prompt_path(path: str) -> Path:
    path = _validate_role_prompt_path(path)
    root = _roles_root()
    target = (root / Path(path)).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="invalid role prompt path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="role prompt not found")
    return target


def _validate_template_content(name: str, content: str) -> None:
    required_tokens = PROMPT_REQUIRED_TOKENS_BY_GROUP.get(DEFAULT_PROMPT_GROUP, DEFAULT_PROMPT_REQUIRED_TOKENS)
    missing = [token for token in required_tokens.get(name, ()) if token not in content]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"prompt template {name} missing placeholders: {', '.join(missing)}",
        )


def _detail_for_group() -> dict[str, Any]:
    if not is_complete_prompt_group_dir(_default_group_dir()):
        raise HTTPException(status_code=400, detail="default prompt templates missing resource: FILE_OUTPUTS.md")
    try:
        return load_prompt_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _list_role_prompt_names() -> list[str]:
    root = _roles_root()
    if not root.is_dir():
        return []
    names: list[str] = []
    for path in root.rglob("*.md"):
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        names.append(path.relative_to(root).as_posix())
    return sorted(names)


def _detail_for_role_prompts() -> dict[str, Any]:
    prompts: dict[str, str] = {}
    sha256: dict[str, str] = {}
    for name in _list_role_prompt_names():
        content = _role_prompt_path(name).read_text(encoding="utf-8")
        prompts[name] = content
        sha256[name] = _text_sha256(content)
    return {
        "role_names": list(prompts.keys()),
        "roles": prompts,
        "role_sha256": sha256,
    }


@router.get("/prompt-templates", response_model=PromptGroupDetail)
def read_prompt_group():
    return _detail_for_group()


@router.get("/role-prompts", response_model=RolePromptDetail)
def read_role_prompts():
    return _detail_for_role_prompts()


@router.put("/prompt-templates/{name}", response_model=PromptGroupDetail)
def update_prompt_template_legacy(
    name: str,
    body: PromptGroupTemplateUpdate,
    _superuser=Depends(current_active_superuser),
):
    if "/" in name:
        raise HTTPException(status_code=400, detail="invalid prompt template name")
    target = _template_path(name)
    _validate_template_content(name, body.content)
    target.write_text(body.content, encoding="utf-8")
    return _detail_for_group()


@router.put("/role-prompts/{role_path:path}", response_model=RolePromptDetail)
def update_role_prompt(
    role_path: str,
    body: PromptGroupTemplateUpdate,
    _superuser=Depends(current_active_superuser),
):
    target = _role_prompt_path(role_path)
    target.write_text(body.content, encoding="utf-8")
    return _detail_for_role_prompts()


@router.put("/prompt-templates/templates/{template_path:path}", response_model=PromptGroupDetail)
def update_prompt_template(
    template_path: str,
    body: PromptGroupTemplateUpdate,
    _superuser=Depends(current_active_superuser),
):
    name = _validate_template_name(template_path)
    target = _template_path(name)
    _validate_template_content(name, body.content)
    target.write_text(body.content, encoding="utf-8")
    return _detail_for_group()
