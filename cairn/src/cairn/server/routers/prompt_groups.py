from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
import yaml

import cairn.dispatcher.prompts as prompt_package
from cairn.dispatcher.capability_constants import CAPABILITY_ROOT
from cairn.dispatcher.tasks.instruction_files import render_task_instruction_files
from cairn.dispatcher.workers.base import WorkerExecutionContext
from cairn.server.config.files import _overwrite_yaml, _text_sha256, resources_yaml_path, save_resources_data
from cairn.server.config.roles import set_role_default_skills_in_data
from cairn.server.execution_config.prompt_snapshot import is_complete_prompt_group_dir, load_prompt_snapshot
from cairn.server.security.deps import current_active_superuser
from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS, PROMPT_REQUIRED_TOKENS_BY_GROUP
from cairn.shared.config.role_models import normalize_default_skill_ids

router = APIRouter(tags=["prompt-groups"])
DEFAULT_PROMPT_GROUP = "default"


class PromptGroupTemplateUpdate(BaseModel):
    content: str


class RolePromptSettingsUpdateRequest(BaseModel):
    content: str
    default_skill_ids: list[str] = Field(default_factory=list)

    @field_validator("default_skill_ids")
    @classmethod
    def validate_default_skill_ids(cls, value: list[str]) -> list[str]:
        return normalize_default_skill_ids(value)


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
    role_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)
    role_metadata_error: str | None = None


class PromptInstructionPreviewFile(BaseModel):
    path: str
    content: str
    sha256: str
    writable: bool


class PromptInstructionPreviewPhase(BaseModel):
    phase: str
    task_instance_id: str
    files: list[PromptInstructionPreviewFile]


class PromptInstructionPreviewResponse(BaseModel):
    phases: list[PromptInstructionPreviewPhase]


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
    metadata, metadata_error = _role_prompt_metadata(prompts.keys())
    return {
        "role_names": list(prompts.keys()),
        "roles": prompts,
        "role_sha256": sha256,
        "role_metadata": metadata,
        "role_metadata_error": metadata_error,
    }


def _instruction_preview_for_phase(phase: str) -> PromptInstructionPreviewPhase:
    task_instance_id = "{task_instance_id}"
    instruction_root = f"{CAPABILITY_ROOT}/{{project_safe_id}}/{task_instance_id}/instructions"
    paths, files = render_task_instruction_files(
        project=None,
        project_id="{project_id}",
        task_type=phase,
        task_instance_id=task_instance_id,
        role_instructions="{selected role prompt}",
        capability_instructions="{selected_mcp_ids}",
        context=WorkerExecutionContext(mcp_servers=[{"id": "{selected_mcp_ids}"}]),
        instruction_root=instruction_root,
        project_origin="{origin}",
        project_goal="{goal}",
    )
    ordered_paths = [
        (paths.agents_md_path, "AGENTS.md"),
        (paths.claude_md_path, "CLAUDE.md"),
        (paths.project_context_path, "context/project.md"),
        (paths.phase_context_path, "context/phase.md"),
        (paths.capabilities_context_path, "context/capabilities.md"),
        (paths.policy_path, "context/policy.json"),
    ]
    return PromptInstructionPreviewPhase(
        phase=phase,
        task_instance_id=task_instance_id,
        files=[
            PromptInstructionPreviewFile(
                path=relative_path,
                content=files[absolute_path],
                sha256=_text_sha256(files[absolute_path]),
                writable=False,
            )
            for absolute_path, relative_path in ordered_paths
        ],
    )


def _instruction_previews() -> PromptInstructionPreviewResponse:
    return PromptInstructionPreviewResponse(
        phases=[_instruction_preview_for_phase(phase) for phase in ("bootstrap", "reason", "explore")]
    )


def _role_prompt_metadata(prompt_names: Any) -> tuple[dict[str, dict[str, Any]], str | None]:
    names = list(prompt_names)
    try:
        data = yaml.safe_load(resources_yaml_path().read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - prompt content remains editable when metadata is broken
        return {}, f"failed to load role metadata: {exc}"
    if not isinstance(data, dict):
        return {}, "failed to load role metadata: config.resources.yaml must contain a mapping"
    roles_raw = data.get("roles")
    roles = roles_raw if isinstance(roles_raw, list) else []
    metadata: dict[str, dict[str, Any]] = {}
    try:
        for role in roles:
            if not isinstance(role, dict):
                continue
            role_id = str(role.get("id") or "").strip()
            if not role_id:
                continue
            prompt_path = _prompt_path_for_role(role)
            if prompt_path not in names:
                continue
            metadata[prompt_path] = {
                "role_id": role_id,
                "name": str(role.get("name") or role_id),
                "default_skill_ids": _normalize_metadata_skill_ids(role.get("default_skill_ids") or []),
                "available": bool(role.get("available", True)),
            }
    except ValueError as exc:
        return {}, f"failed to load role metadata: {exc}"
    return metadata, None


def _prompt_path_for_role(role: dict[str, Any]) -> str:
    role_id = str(role.get("id") or "").strip()
    data_path = resources_yaml_path()
    root = _roles_root()
    if role.get("source_path"):
        path = Path(str(role["source_path"]))
        if not path.is_absolute():
            path = data_path.parent / path
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    return f"{role_id}/ROLE.md"


def _normalize_metadata_skill_ids(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return normalize_default_skill_ids(items)


def _load_resources_data_for_role_prompt_settings() -> dict[str, Any]:
    try:
        data = yaml.safe_load(resources_yaml_path().read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"failed to load role metadata: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(500, "failed to load role metadata: config.resources.yaml must contain a mapping")
    return data


def _role_for_id(data: dict[str, Any], role_id: str) -> dict[str, Any]:
    roles_raw = data.get("roles")
    roles = roles_raw if isinstance(roles_raw, list) else []
    target = next((role for role in roles if isinstance(role, dict) and role.get("id") == role_id), None)
    if target is None:
        raise HTTPException(404, f"role not found: {role_id}")
    return target


@router.get("/prompt-templates", response_model=PromptGroupDetail)
def read_prompt_group():
    return _detail_for_group()


@router.get("/role-prompts", response_model=RolePromptDetail)
def read_role_prompts():
    return _detail_for_role_prompts()


@router.get("/prompt-instruction-previews", response_model=PromptInstructionPreviewResponse)
def read_prompt_instruction_previews():
    return _instruction_previews()


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


@router.put("/roles/admin/{role_id}/prompt-settings", response_model=RolePromptDetail)
def update_role_prompt_settings(
    role_id: str,
    body: RolePromptSettingsUpdateRequest,
    _superuser=Depends(current_active_superuser),
):
    data = _load_resources_data_for_role_prompt_settings()
    role = _role_for_id(data, role_id)
    role_prompt_path = _prompt_path_for_role(role)
    target = _role_prompt_path(role_prompt_path)
    set_role_default_skills_in_data(data, role_id, body.default_skill_ids)
    original_resources = resources_yaml_path().read_text(encoding="utf-8")
    original = target.read_text(encoding="utf-8")
    target.write_text(body.content, encoding="utf-8")
    try:
        save_resources_data(data)
    except Exception:
        target.write_text(original, encoding="utf-8")
        _overwrite_yaml(resources_yaml_path(), original_resources)
        raise
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
