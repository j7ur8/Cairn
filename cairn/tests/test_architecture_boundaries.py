from __future__ import annotations

import ast
import inspect
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "cairn"
MIGRATIONS = ROOT / "migrations" / "versions"
ARCHITECTURE_PATH = ROOT.parent / "AI" / "ARCHITECTURE.md"


def _py_files(path: Path) -> list[Path]:
    return sorted(file for file in path.rglob("*.py") if "__pycache__" not in file.parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _revision_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        strings: list[str] = []
        for item in value:
            strings.extend(_revision_strings(item))
        return strings
    return []


def test_domain_has_no_sql_fastapi_or_repository_imports() -> None:
    forbidden_tokens = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "sql.", "text(")
    offenders: list[str] = []
    for path in _py_files(SRC / "server" / "domain"):
        source = path.read_text(encoding="utf-8")
        imports = _imports(path)
        if any(name == "fastapi" or name.startswith("fastapi.") for name in imports):
            offenders.append(f"{path.relative_to(ROOT)} imports fastapi")
        if any(name == "cairn.server.repositories" or name.startswith("cairn.server.repositories.") for name in imports):
            offenders.append(f"{path.relative_to(ROOT)} imports repository")
        if any(token in source for token in forbidden_tokens):
            offenders.append(f"{path.relative_to(ROOT)} contains SQL token")
    assert offenders == []


def test_routers_do_not_use_direct_sql_helpers() -> None:
    forbidden = ("fetchone", "fetchall", "execute(", "repositories.sql", "sql.")
    allowed = {"auth.py"}
    offenders: list[str] = []
    for path in _py_files(SRC / "server" / "routers"):
        if path.name in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert offenders == []


def test_routers_do_not_import_repositories_directly() -> None:
    offenders: list[str] = []
    for path in _py_files(SRC / "server" / "routers"):
        if path.name == "auth.py":
            continue
        imports = _imports(path)
        for name in imports:
            if name == "cairn.server.repositories" or name.startswith("cairn.server.repositories."):
                offenders.append(f"{path.relative_to(ROOT)} imports {name}")
    assert offenders == []


def test_mappers_are_sql_free() -> None:
    forbidden = ("repositories.sql", "fetchone", "fetchall", "execute(", "SELECT ", "INSERT ", "UPDATE ", "DELETE ")
    offenders: list[str] = []
    for path in _py_files(SRC / "server" / "mappers"):
        source = path.read_text(encoding="utf-8")
        imports = _imports(path)
        if any(name == "cairn.server.repositories" or name.startswith("cairn.server.repositories.") for name in imports):
            offenders.append(f"{path.relative_to(ROOT)} imports repository")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert offenders == []


def test_application_core_does_not_open_sessions_implicitly() -> None:
    allowed = {
        "project_commands.py",  # explicit best-effort observability cleanup helper.
        "replay/orchestration.py",  # transaction/file-compensation boundary.
    }
    offenders: list[str] = []
    app_dir = SRC / "server" / "application"
    for path in _py_files(app_dir):
        relative = path.relative_to(app_dir).as_posix()
        if relative in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if "db.session_scope(" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_observability_sql_stays_in_repository_or_query_modules() -> None:
    allowed_suffixes = ("_repository.py", "_query.py")
    allowed_files = {"retention.py"}  # YAML/config orchestration opens a session but does not own SQL.
    forbidden = ("from cairn.server.repositories import sql", "sql.", "conn.execute(", "self.conn.execute(")
    offenders: list[str] = []
    for path in _py_files(SRC / "server" / "observability"):
        if path.name in allowed_files or path.name.endswith(allowed_suffixes):
            continue
        source = path.read_text(encoding="utf-8")
        imports = _imports(path)
        if any(name == "sqlalchemy" or name.startswith("sqlalchemy.") for name in imports):
            offenders.append(f"{path.relative_to(ROOT)} imports sqlalchemy")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert offenders == []


def test_scheduler_collaborators_do_not_depend_on_dispatcher_loop() -> None:
    scheduler_dir = SRC / "dispatcher" / "scheduler"
    offenders: list[str] = []
    for path in _py_files(scheduler_dir):
        if path.name == "loop.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "DispatcherLoop" in source or "scheduler.loop" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_task_submitter_delegates_claim_and_registration_details() -> None:
    path = SRC / "dispatcher" / "scheduler" / "task_submitter.py"
    source = path.read_text(encoding="utf-8")
    forbidden = (
        "client.claim(",
        "client.claim_reason(",
        "runtime.add(",
        "def _claim_intent",
        "def _claim_reason",
        "def _submit_task",
    )
    offenders = [token for token in forbidden if token in source]
    assert offenders == []


def test_task_runner_entrypoints_use_context_objects() -> None:
    from cairn.dispatcher.tasks.bootstrap import run_bootstrap_task
    from cairn.dispatcher.tasks.explore import run_explore_task
    from cairn.dispatcher.tasks.reason import run_reason_task

    offenders: list[str] = []
    for runner in (run_bootstrap_task, run_explore_task, run_reason_task):
        params = [
            param
            for param in inspect.signature(runner).parameters.values()
            if param.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(params) > 2:
            offenders.append(f"{runner.__module__}.{runner.__name__} has {len(params)} positional params")
    assert offenders == []


def test_task_modules_depend_on_container_runtime_protocol_not_manager() -> None:
    offenders: list[str] = []
    tasks_dir = SRC / "dispatcher" / "tasks"
    allowed = {"context.py"}
    forbidden = (
        "from cairn.dispatcher.runtime.containers import ContainerManager",
        "cairn.dispatcher.runtime.containers",
    )
    for path in _py_files(tasks_dir):
        if path.name in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert offenders == []


def test_removed_internal_import_paths_do_not_reappear() -> None:
    forbidden = (
        "cairn.dispatcher.tasks.common",
        "cairn.server.schemas.intents",
        "cairn.server.schemas.capabilities",
    )
    offenders: list[str] = []
    for path in _py_files(SRC):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert offenders == []


def test_known_small_import_cycles_do_not_reappear() -> None:
    """Keep cycle-prone boundaries acyclic after the decomposition cleanup."""
    offenders: list[str] = []
    checks = {
        SRC / "dispatcher" / "capability_mcp.py": (
            "cairn.dispatcher.capability_probe",
            "from cairn.dispatcher.capability_probe",
        ),
        SRC / "dispatcher" / "capability_probe.py": (
            "cairn.dispatcher.capability_mcp",
            "from cairn.dispatcher.capability_mcp",
        ),
        SRC / "shared" / "config" / "loader.py": (
            "from cairn.shared.config.root import DispatchConfig",
        ),
    }
    for path, forbidden_tokens in checks.items():
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert offenders == []


def test_dto_boundary_docs_stay_visible() -> None:
    server_models = (SRC / "server" / "schemas" / "__init__.py").read_text(encoding="utf-8")
    shared_contracts = (SRC / "shared" / "contracts" / "__init__.py").read_text(encoding="utf-8")
    assert "Server-private HTTP request/response" in server_models
    assert "shared with the dispatcher" in server_models
    assert "Wire contracts shared across Cairn processes" in shared_contracts
    assert "Server-only" in shared_contracts


def test_removed_compatibility_import_shims_stay_removed() -> None:
    from cairn.dispatcher.workers.adapters.claude_code import ClaudeCodeDriver as CanonicalClaudeCodeDriver
    from cairn.server.application.project_queries import _decode_cursor as canonical_decode_cursor
    from cairn.server.schemas import CreateProjectRequest
    from cairn.server.schemas.ai_profiles import AiProfileCreate

    assert CanonicalClaudeCodeDriver.__name__ == "ClaudeCodeDriver"
    assert callable(canonical_decode_cursor)
    assert CreateProjectRequest.__name__ == "CreateProjectRequest"
    assert AiProfileCreate.__name__ == "AiProfileCreate"

    removed_modules = (
        "cairn.dispatcher.workers.adapters.claudecode",
        "cairn.server.application.project_read",
        "cairn.server.models_pkg",
        "cairn.server.models_pkg.ai_profiles",
    )
    available: list[str] = []
    for module in removed_modules:
        try:
            spec = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            spec = None
        if spec is not None:
            available.append(module)
    assert available == []

    removed_paths = (
        SRC / "dispatcher" / "workers" / "adapters" / "claudecode.py",
        SRC / "server" / "application" / "project_read.py",
        SRC / "server" / "models_pkg",
    )
    assert [str(path.relative_to(ROOT)) for path in removed_paths if path.exists()] == []


def test_internal_imports_use_canonical_paths_not_removed_shims() -> None:
    forbidden = (
        "cairn.dispatcher.workers.adapters.claudecode",
        "cairn.server.application.project_read",
        "cairn.server.models_pkg",
    )
    offenders: list[str] = []
    for path in _py_files(SRC):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert offenders == []


def test_alembic_revision_ids_fit_default_version_column() -> None:
    offenders: list[str] = []
    for path in sorted(MIGRATIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}
            ]
            if not names:
                continue
            value = ast.literal_eval(node.value)
            for name in names:
                for revision in _revision_strings(value):
                    if len(revision) > 32:
                        offenders.append(f"{path.name}:{name}={revision!r}")
    assert offenders == []


def test_architecture_doc_reflects_alembic_head() -> None:
    """The Alembic head cited in ARCHITECTURE.md must match the latest revision.

    Documentation drift between the migration chain and the architecture doc
    misleads every AI session that reads ARCHITECTURE.md as its primary context.
    This test ensures the doc stays in sync with the actual schema on each
    change to the migrations directory.
    """
    # Resolve the head revision by walking the linear down_revision chain.
    revisions: dict[str, str | None] = {}
    for path in sorted(MIGRATIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    value = ast.literal_eval(node.value)
                    revisions.setdefault(
                        path.name,
                        {"revision": None, "down_revision": None},
                    )[target.id] = value  # type: ignore[index]
    # Linear chain: each revision (except the initial) has a down_revision;
    # the head is the one that no other migration claims as its down_revision.
    ids = {v["revision"] for v in revisions.values() if v["revision"] is not None}
    down_refs = {v["down_revision"] for v in revisions.values() if v["down_revision"] is not None}
    heads = ids - down_refs
    assert len(heads) == 1, f"expected exactly one alembic head, got: {heads!r}"
    head = heads.pop()

    doc = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    assert head in doc, (
        f"ARCHITECTURE.md must reference the current Alembic head {head!r}, "
        f"but it does not. Update the doc."
    )
