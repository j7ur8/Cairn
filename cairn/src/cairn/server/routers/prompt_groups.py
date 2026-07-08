from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from cairn.dispatcher.prompts.layout import (
    COMMON_PROMPT_NAMES,
    PROMPT_PHASES,
    common_prompt_path,
    phase_for_logical_prompt,
    prompt_package_path,
    role_prompt_path,
    validate_phase,
)
from cairn.dispatcher.tasks.instruction_files import (
    RUNTIME_INSTRUCTION_PHASES,
    runtime_instruction_template_path,
    validate_runtime_instruction_phase,
    validate_runtime_instruction_template_path,
)
from cairn.server.config.files import _overwrite_yaml, _text_sha256, resources_yaml_path, save_resources_data
from cairn.server.config.roles import set_role_default_skills_in_data
from cairn.server.execution_config.prompt_snapshot import is_complete_prompt_group_dir, load_prompt_snapshot
from cairn.server.security.deps import current_active_superuser
from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS, PROMPT_REQUIRED_TOKENS_BY_GROUP
from cairn.shared.config.role_models import normalize_default_skill_ids

router = APIRouter(tags=["prompt-groups"])


class PromptGroupTemplateUpdate(BaseModel):
    content: str


class RolePromptSettingsUpdateRequest(BaseModel):
    content: str
    default_skill_ids: list[str] = Field(default_factory=list)
    phase: str = "bootstrap"

    @field_validator("default_skill_ids")
    @classmethod
    def validate_default_skill_ids(cls, value: list[str]) -> list[str]:
        return normalize_default_skill_ids(value)


class PromptGroupDetail(BaseModel):
    prompt_group: str = "phase-first"
    prompt_names: list[str]
    prompts: dict[str, str]
    prompt_sha256: dict[str, str]
    prompts_sha256: str
    resources: list[dict[str, Any]] = Field(default_factory=list)


class RolePromptDetail(BaseModel):
    role_names: list[str]
    roles: dict[str, str]
    role_sha256: dict[str, str]
    role_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)
    role_metadata_error: str | None = None
    resources: list[dict[str, Any]] = Field(default_factory=list)


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
    resources: list[dict[str, Any]] = Field(default_factory=list)


def _prompts_root() -> Path:
    try:
        return prompt_package_path()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="prompt resources are not writable files") from exc


def _default_group_dir() -> Path:
    return _prompts_root()


def _validate_template_name(name: str) -> str:
    parts = name.split("/")
    if not name or name.startswith("/") or "\\" in name or parts != [part for part in parts if part] or ".." in parts:
        raise HTTPException(status_code=400, detail="invalid prompt template name")
    if not name.endswith(".md"):
        raise HTTPException(status_code=400, detail="invalid prompt template name")
    if name not in COMMON_PROMPT_NAMES:
        raise HTTPException(status_code=404, detail="prompt template not found")
    return name


def _template_path(name: str) -> Path:
    name = _validate_template_name(name)
    root = _prompts_root()
    target = common_prompt_path(name, root)
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="prompt template not found")
    return target


def _validate_role_prompt_path(path: str) -> str:
    parts = path.split("/")
    if not path or path.startswith("/") or "\\" in path or parts != [part for part in parts if part] or ".." in parts:
        raise HTTPException(status_code=400, detail="invalid role prompt path")
    if len(parts) != 3 or parts[1] != "roles" or not path.endswith(".md"):
        raise HTTPException(status_code=400, detail="invalid role prompt path")
    try:
        validate_phase(parts[0])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid role prompt path") from exc
    return path


def _role_prompt_path(path: str) -> Path:
    path = _validate_role_prompt_path(path)
    root = _prompts_root()
    parts = path.split("/")
    target = role_prompt_path(parts[0], Path(parts[2]).stem, root)
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="invalid role prompt path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="role prompt not found")
    return target


def _validate_template_content(name: str, content: str) -> None:
    required_tokens = PROMPT_REQUIRED_TOKENS_BY_GROUP.get("default", DEFAULT_PROMPT_REQUIRED_TOKENS)
    missing = [token for token in required_tokens.get(name, ()) if token not in content]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"prompt template {name} missing placeholders: {', '.join(missing)}",
        )


def _detail_for_group() -> dict[str, Any]:
    if not is_complete_prompt_group_dir(_default_group_dir()):
        raise HTTPException(status_code=400, detail="prompt templates missing required resource")
    try:
        snapshot = load_prompt_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    prompts: dict[str, str] = {}
    prompt_sha256: dict[str, str] = {}
    for name in COMMON_PROMPT_NAMES:
        target = _template_path(name)
        content = target.read_text(encoding="utf-8")
        prompts[name] = content
        prompt_sha256[name] = _text_sha256(content)
    resources = []
    for name in COMMON_PROMPT_NAMES:
        phase = phase_for_logical_prompt(name)
        logical_name = Path(name).name
        resources.append(
            {
                "phase": phase,
                "category": "common",
                "path": name,
                "logical_name": logical_name,
                "content": prompts[name],
                "sha256": prompt_sha256[name],
                "writable": True,
            }
        )
    return {
        **snapshot,
        "prompt_group": "phase-first",
        "prompt_names": list(COMMON_PROMPT_NAMES),
        "prompts": prompts,
        "prompt_sha256": prompt_sha256,
        "resources": resources,
    }


def _list_role_prompt_names() -> list[str]:
    root = _prompts_root()
    names: list[str] = []
    for phase in PROMPT_PHASES:
        role_root = root / phase / "roles"
        if not role_root.is_dir():
            continue
        for path in role_root.glob("*.md"):
            if path.name.startswith("."):
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
        "resources": [
            {
                "phase": name.split("/", 1)[0],
                "category": "roles",
                "path": name,
                "logical_name": Path(name).name,
                "content": prompts[name],
                "sha256": sha256[name],
                "writable": True,
                "role_metadata": metadata.get(name),
            }
            for name in prompts
        ],
    }


def _instruction_preview_for_phase(phase: str) -> PromptInstructionPreviewPhase:
    task_instance_id = "{task_instance_id}"
    target = _runtime_instruction_template_path(phase, "Instruction.md")
    content = target.read_text(encoding="utf-8")
    return PromptInstructionPreviewPhase(
        phase=phase,
        task_instance_id=task_instance_id,
        files=[
            PromptInstructionPreviewFile(
                path="Instruction.md",
                content=content,
                sha256=_text_sha256(content),
                writable=True,
            )
        ],
    )


def _instruction_previews() -> PromptInstructionPreviewResponse:
    phases = [_instruction_preview_for_phase(phase) for phase in RUNTIME_INSTRUCTION_PHASES]
    resources = [
        {
            "phase": phase.phase,
            "category": "instruction",
            "path": file.path,
            "logical_name": file.path,
            "content": file.content,
            "sha256": file.sha256,
            "writable": file.writable,
        }
        for phase in phases
        for file in phase.files
    ]
    return PromptInstructionPreviewResponse(phases=phases, resources=resources)


def _runtime_instruction_template_path(phase: str, template_path: str) -> Path:
    try:
        phase = validate_runtime_instruction_phase(phase)
        if template_path == "Instruction.md":
            return runtime_instruction_template_path(phase, "AGENTS.md").with_name("Instruction.md")
        template_path = validate_runtime_instruction_template_path(template_path)
        return runtime_instruction_template_path(phase, template_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="runtime instruction template not found") from exc


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
            for phase in PROMPT_PHASES:
                prompt_path = f"{phase}/roles/{role_id}.md"
                if prompt_path not in names:
                    continue
                metadata[prompt_path] = {
                    "role_id": role_id,
                    "phase": phase,
                    "name": str(role.get("name") or role_id),
                    "default_skill_ids": _normalize_metadata_skill_ids(role.get("default_skill_ids") or []),
                    "available": bool(role.get("available", True)),
                }
    except ValueError as exc:
        return {}, f"failed to load role metadata: {exc}"
    return metadata, None


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


@router.put("/prompt-instruction-previews/{phase}/{template_path:path}", response_model=PromptInstructionPreviewResponse)
def update_prompt_instruction_preview(
    phase: str,
    template_path: str,
    body: PromptGroupTemplateUpdate,
    _superuser=Depends(current_active_superuser),
):
    target = _runtime_instruction_template_path(phase, template_path)
    if target.name != "Instruction.md":
        raise HTTPException(status_code=400, detail="only Instruction.md is editable")
    target.write_text(body.content, encoding="utf-8")
    target.with_name("AGENTS.md").write_text(body.content, encoding="utf-8")
    target.with_name("CLAUDE.md").write_text(body.content, encoding="utf-8")
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
    _role_for_id(data, role_id)
    try:
        phase = validate_phase(body.phase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid prompt phase") from exc
    role_prompt_path = f"{phase}/roles/{role_id}.md"
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
