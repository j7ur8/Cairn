from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "cairn"
MIGRATIONS = ROOT / "migrations" / "versions"


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


def test_removed_internal_import_paths_do_not_reappear() -> None:
    forbidden = (
        "cairn.dispatcher.tasks.common",
        "cairn.server.models_pkg.intents",
        "cairn.server.models_pkg.capabilities",
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
