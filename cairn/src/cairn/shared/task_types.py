"""Task type registry.

Keeps the built-in task type names in one place. New task types
register themselves at import time via
:func:`register`; the rest of the system reads
:data:`TASK_TYPE_REGISTRY` to validate user input.

The registry also carries a JSON Schema fragment for the task's
parameters, so a future UI can render a form for an arbitrary
``task_type`` without code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class TaskTypeSpec:
    """A single registered task type.

    Attributes:
        name: canonical short name, e.g. ``"bootstrap"``.
        description: human-readable blurb for the UI.
        json_schema: JSON Schema fragment describing the task
            parameters; defaults to ``{}`` (no extra fields).
        model_class: optional Pydantic model class that validates
            the task's parameter payload. ``None`` means "no
            parameters accepted" - the router must validate the
            concrete shape against the model's own schema.
    """

    name: str
    description: str = ""
    json_schema: dict[str, Any] = field(default_factory=dict)
    model_class: type | None = None


class TaskTypeRegistry:
    """Process-wide task type registry.

    The registry is intentionally a thin in-memory dict rather than
    something like a plug-in entry point: cairn ships its own task
    types and we do not want a third-party ``task_type`` to be
    loaded by accident. Callers add their task types at import
    time (see ``_register_builtins`` below).
    """

    def __init__(self) -> None:
        self._specs: dict[str, TaskTypeSpec] = {}

    def register(self, spec: TaskTypeSpec) -> TaskTypeSpec:
        if not spec.name or not isinstance(spec.name, str):
            raise ValueError("task type name must be a non-empty string")
        if spec.name in self._specs:
            # Re-registration is allowed at import time and is
            # treated as idempotent; the second call is a no-op.
            return self._specs[spec.name]
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> TaskTypeSpec | None:
        return self._specs.get(name)

    def names(self) -> tuple[str, ...]:
        # Stable order: registration order. Tests rely on this.
        return tuple(self._specs)

    def specs(self) -> Iterable[TaskTypeSpec]:
        return tuple(self._specs.values())

    def is_valid(self, name: str) -> bool:
        return name in self._specs

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._specs

    def __len__(self) -> int:
        return len(self._specs)


TASK_TYPE_REGISTRY = TaskTypeRegistry()
BUILTIN_TASK_TYPES: tuple[tuple[str, str], ...] = (
    ("bootstrap", "Initial project setup: scaffold the project graph."),
    ("explore", "Generate a new intent / fact chain."),
    ("reason", "Maintain the project's reason / trigger state."),
)


def _register_task_type(
    name: str,
    *,
    description: str = "",
    json_schema: dict[str, Any] | None = None,
    model_class: type | None = None,
) -> TaskTypeSpec:
    """Convenience wrapper around :meth:`TaskTypeRegistry.register`.

    Used as a decorator-free helper:

        _ = _register_task_type("bootstrap", description="...")
    """
    return TASK_TYPE_REGISTRY.register(
        TaskTypeSpec(
            name=name,
            description=description,
            json_schema=json_schema or {},
            model_class=model_class,
        )
    )


def _register_builtins() -> None:
    """Register the task types cairn ships with.

    Imported eagerly so :data:`TASK_TYPE_REGISTRY.names()` is
    non-empty by the time the first model validation runs.
    """
    for name, description in BUILTIN_TASK_TYPES:
        _register_task_type(name, description=description)


_register_builtins()


def is_known_task_type(name: str) -> bool:
    """Helper for Pydantic ``field_validator`` and dispatcher side checks."""
    return TASK_TYPE_REGISTRY.is_valid(name)


def builtin_task_type_names() -> tuple[str, ...]:
    return tuple(name for name, _description in BUILTIN_TASK_TYPES)


def default_worker_task_type_names() -> tuple[str, ...]:
    return builtin_task_type_names()


def default_capability_task_type_names() -> tuple[str, ...]:
    return tuple(name for name in builtin_task_type_names() if name != "reason")
