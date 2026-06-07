from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from cairn.server.sqlite_diagnostics import (
    database_error_detail,
    file_state,
    passive_checkpoint,
    quick_check as run_quick_check,
    truncate_checkpoint,
)

DEFAULT_DB = Path.home() / ".local" / "share" / "cairn" / "cairn.db"
SQLITE_TIMEOUT_SECONDS = 5.0
SQLITE_BUSY_TIMEOUT_MS = 5000

LOG = logging.getLogger(__name__)

_db_path: Path | None = None
_local = threading.local()

SCHEMA = """\
CREATE TABLE IF NOT EXISTS settings (
    intent_timeout INTEGER NOT NULL DEFAULT 15,
    reason_timeout INTEGER NOT NULL DEFAULT 15
);

INSERT OR IGNORE INTO settings (rowid, intent_timeout, reason_timeout) VALUES (1, 15, 15);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    reason_worker TEXT,
    reason_run_id TEXT,
    reason_trigger TEXT,
    reason_started_at TEXT,
    reason_last_heartbeat_at TEXT
);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS intents (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    to_fact_id TEXT,
    description TEXT NOT NULL,
    creator TEXT NOT NULL,
    worker TEXT,
    last_heartbeat_at TEXT,
    created_at TEXT NOT NULL,
    concluded_at TEXT,
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS intent_sources (
    intent_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    PRIMARY KEY (intent_id, project_id, fact_id),
    FOREIGN KEY (intent_id, project_id) REFERENCES intents(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS hints (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    creator TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO counters (name, value) VALUES ('project', 0);

CREATE TABLE IF NOT EXISTS scoped_counters (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, kind)
);

CREATE TABLE IF NOT EXISTS capability_catalog (
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_types TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    detail TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);

CREATE TABLE IF NOT EXISTS project_capabilities (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, kind, capability_id)
);

CREATE TABLE IF NOT EXISTS role_catalog (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    task_types TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    detail TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_roles (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    role_id TEXT NOT NULL,
    role_name TEXT NOT NULL,
    role_prompt TEXT NOT NULL,
    role_prompt_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replay_runs (
    id TEXT PRIMARY KEY,
    source_project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    replay_project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    completion_description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS replay_fact_map (
    run_id TEXT NOT NULL REFERENCES replay_runs(id) ON DELETE CASCADE,
    source_fact_id TEXT NOT NULL,
    replay_fact_id TEXT NOT NULL,
    PRIMARY KEY (run_id, source_fact_id)
);

CREATE TABLE IF NOT EXISTS replay_steps (
    run_id TEXT NOT NULL REFERENCES replay_runs(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    source_intent_id TEXT NOT NULL,
    source_to_fact_id TEXT NOT NULL,
    replay_intent_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT,
    concluded_at TEXT,
    PRIMARY KEY (run_id, step_index),
    UNIQUE (run_id, source_intent_id)
);

CREATE TABLE IF NOT EXISTS proxies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('socks5','http','https')),
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT,
    password TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_reason_state (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    trigger TEXT NOT NULL DEFAULT '',
    trigger_hash TEXT NOT NULL DEFAULT '',
    fact_count INTEGER NOT NULL DEFAULT 0,
    hint_count INTEGER NOT NULL DEFAULT 0,
    open_intent_count INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL DEFAULT 'initial',
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    next_retry_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_profile_models (
    profile_id TEXT NOT NULL REFERENCES ai_profiles(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, model)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS migration_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    sql TEXT NOT NULL,
    error TEXT NOT NULL,
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

MIGRATIONS: list[tuple[str, str]] = [
    (
        "20260604_001_core_indexes",
        """
        CREATE INDEX IF NOT EXISTS idx_facts_project_id ON facts(project_id);
        CREATE INDEX IF NOT EXISTS idx_hints_project_id ON hints(project_id);
        CREATE INDEX IF NOT EXISTS idx_intents_project_open_worker ON intents(project_id, concluded_at, worker);
        CREATE INDEX IF NOT EXISTS idx_intents_project_to_fact ON intents(project_id, to_fact_id);
        CREATE INDEX IF NOT EXISTS idx_intent_sources_project_fact ON intent_sources(project_id, fact_id);
        CREATE INDEX IF NOT EXISTS idx_project_capabilities_project_kind ON project_capabilities(project_id, kind);
        CREATE INDEX IF NOT EXISTS idx_replay_steps_run_status ON replay_steps(run_id, status);
        """,
    ),
    (
        "20260604_002_ai_profiles",
        """
        CREATE TABLE IF NOT EXISTS ai_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            worker_type TEXT NOT NULL CHECK(worker_type IN ('codex','claudecode')),
            provider TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL,
            api_key_env TEXT NOT NULL,
            available INTEGER NOT NULL DEFAULT 1,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_ai_profiles (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            profile_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('primary','fallback')),
            position INTEGER NOT NULL,
            snapshot_name TEXT NOT NULL,
            snapshot_worker_type TEXT NOT NULL,
            snapshot_provider TEXT NOT NULL DEFAULT '',
            snapshot_base_url TEXT NOT NULL DEFAULT '',
            snapshot_model TEXT NOT NULL,
            snapshot_api_key_env TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, profile_id, role)
        );

        CREATE INDEX IF NOT EXISTS idx_project_ai_profiles_project_role_position ON project_ai_profiles(project_id, role, position);
        """,
    ),

    (
        "20260604_002b_ai_profile_seed",
        """
        ALTER TABLE ai_profiles ADD COLUMN seeded_from_worker TEXT;
        ALTER TABLE ai_profiles ADD COLUMN healthcheck_timeout REAL NOT NULL DEFAULT 1.0;
        ALTER TABLE ai_profiles ADD COLUMN last_health_ok INTEGER;
        ALTER TABLE ai_profiles ADD COLUMN last_health_message TEXT NOT NULL DEFAULT '';
        ALTER TABLE ai_profiles ADD COLUMN last_health_at TEXT;

        CREATE INDEX IF NOT EXISTS idx_ai_profiles_seeded_from_worker
            ON ai_profiles(seeded_from_worker)
            WHERE seeded_from_worker IS NOT NULL;
        """,
    ),
    (
        "20260604_003_task_ai_profiles",
        """
        ALTER TABLE project_ai_profiles ADD COLUMN task_type TEXT NOT NULL DEFAULT 'legacy';

        CREATE TABLE project_ai_profiles_v2 (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            profile_id TEXT NOT NULL,
            task_type TEXT NOT NULL DEFAULT 'legacy',
            role TEXT NOT NULL CHECK(role IN ('primary','fallback')),
            position INTEGER NOT NULL,
            snapshot_name TEXT NOT NULL,
            snapshot_worker_type TEXT NOT NULL,
            snapshot_provider TEXT NOT NULL DEFAULT '',
            snapshot_base_url TEXT NOT NULL DEFAULT '',
            snapshot_model TEXT NOT NULL,
            snapshot_api_key_env TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, task_type, profile_id, role)
        );

        INSERT INTO project_ai_profiles_v2 (
            project_id, profile_id, task_type, role, position,
            snapshot_name, snapshot_worker_type, snapshot_provider,
            snapshot_base_url, snapshot_model, snapshot_api_key_env, created_at
        )
        SELECT
            project_id, profile_id, task_type, role, position,
            snapshot_name, snapshot_worker_type, snapshot_provider,
            snapshot_base_url, snapshot_model, snapshot_api_key_env, created_at
        FROM project_ai_profiles;

        DROP TABLE project_ai_profiles;
        ALTER TABLE project_ai_profiles_v2 RENAME TO project_ai_profiles;

        CREATE INDEX IF NOT EXISTS idx_project_ai_profiles_project_task_role_position
            ON project_ai_profiles(project_id, task_type, role, position);
        """,
    ),
    (
        "20260604_004_reason_state",
        """
        CREATE TABLE IF NOT EXISTS project_reason_state (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            trigger TEXT NOT NULL DEFAULT '',
            trigger_hash TEXT NOT NULL DEFAULT '',
            fact_count INTEGER NOT NULL DEFAULT 0,
            hint_count INTEGER NOT NULL DEFAULT 0,
            open_intent_count INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL DEFAULT 'initial',
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            next_retry_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_project_reason_state_retry
            ON project_reason_state(next_retry_at)
            WHERE next_retry_at IS NOT NULL;
        """,
    ),
    (
        "20260604_005_reason_run_id",
        """
        ALTER TABLE projects ADD COLUMN reason_run_id TEXT;
        """,
    ),
    (
        "20260605_006_ai_profile_models",
        """
        CREATE TABLE IF NOT EXISTS ai_profile_models (
            profile_id TEXT NOT NULL REFERENCES ai_profiles(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (profile_id, model)
        );

        CREATE INDEX IF NOT EXISTS idx_ai_profile_models_profile_id
            ON ai_profile_models(profile_id);
        """,
    ),
    (
        "20260605_007_ai_profile_reasoning",
        """
        ALTER TABLE ai_profiles ADD COLUMN model_reasoning_effort TEXT;
        ALTER TABLE project_ai_profiles ADD COLUMN snapshot_reasoning_type TEXT;
        """,
    ),
    (
        "20260605_008_prune_legacy_seeded_ai_profile",
        """
        -- One-time cleanup of the obsolete ``ai_seed_codex_gpt-5_4`` row
        -- (seeded_from_worker = 'codex:gpt-5.4') left over from an older
        -- dispatcher naming convention. ai_profile_models rows are removed
        -- via ON DELETE CASCADE; the explicit DELETE is defensive.
        DELETE FROM ai_profile_models
        WHERE profile_id IN (
            SELECT id FROM ai_profiles
            WHERE id = 'ai_seed_codex_gpt-5_4'
               OR seeded_from_worker = 'codex:gpt-5.4'
        );

        DELETE FROM ai_profiles
        WHERE id = 'ai_seed_codex_gpt-5_4'
           OR seeded_from_worker = 'codex:gpt-5.4';
        """,
    ),
    (
        "20260606_001_ai_profiles_sk",
        """
        -- Add a per-profile secret key column. The dispatcher stops
        -- discarding the resolved token at sync time and pushes the value
        -- here; manual profiles can be populated via the Add/Edit form.
        -- The column is plaintext; the form helper text and the API
        -- contract (write-only ``sk`` on create/update, masked on read)
        -- are the only safeguards.
        ALTER TABLE ai_profiles ADD COLUMN sk TEXT NOT NULL DEFAULT '';
        """,
    ),
    (
        "20260607_001_users",
        """
        -- JWT auth surface. Single-table users with bcrypt hashes; one
        -- superuser is bootstrapped at server startup from env.
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            hashed_password TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_superuser INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    (
        "20260607_002_sk_ciphertext",
        """
        -- Encrypted sk storage. Adds a sibling column to the legacy
        -- plaintext sk so the migration is reversible: we keep writing
        -- sk (for backward compat with any tools that read it
        -- directly), but the new column is what the read path uses.
        --
        -- The dispatcher secret endpoint decrypts on the way out. A
        -- later migration can drop the plaintext column once all
        -- existing deployments have re-synced with the new code path.
        ALTER TABLE ai_profiles ADD COLUMN sk_ciphertext TEXT NOT NULL DEFAULT '';
        """,
    ),
    (
        "20260608_001_capability_admin",
        """
        -- Capability catalog gains source/requires/probe state. ``builtin``
        -- rows come from the dispatcher's catalog sync; ``user`` rows are
        -- created/edited/deleted from the Settings UI.
        ALTER TABLE capability_catalog ADD COLUMN source TEXT NOT NULL DEFAULT 'builtin';
        ALTER TABLE capability_catalog ADD COLUMN requires_ids TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE capability_catalog ADD COLUMN probe_config TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE capability_catalog ADD COLUMN last_probe_status TEXT;
        ALTER TABLE capability_catalog ADD COLUMN last_probe_at TEXT;
        ALTER TABLE capability_catalog ADD COLUMN last_probe_message TEXT NOT NULL DEFAULT '';

        -- Per-task project capability snapshots. The previous flat
        -- ``project_capabilities`` table carried one row per
        -- (project, kind, capability_id) and was used for every
        -- task_type implicitly. The new table keys on task_type and
        -- carries the auto-included sub-skill provenance so the UI
        -- can distinguish "user picked" vs "expanded from requires".
        CREATE TABLE IF NOT EXISTS project_capability_snapshots (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_type TEXT NOT NULL,
            kind TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'selected',
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, task_type, kind, capability_id)
        );
        CREATE INDEX IF NOT EXISTS idx_project_capability_snapshots_project_task
            ON project_capability_snapshots(project_id, task_type);
        """,
    ),
    (
        "20260608_002_capability_legacy_migration",
        """
        -- Move pre-existing rows out of the flat table into per-task
        -- snapshots tagged ``task_type='legacy'``. The UI surfaces a
        -- "migrating" banner for those projects and rewrites the rows
        -- on the next save. A no-op when the flat table is empty
        -- (fresh installs), which keeps the migration idempotent.
        INSERT INTO project_capability_snapshots (
            project_id, task_type, kind, capability_id, source, position, created_at
        )
        SELECT
            pc.project_id,
            'legacy',
            pc.kind,
            pc.capability_id,
            'selected',
            0,
            pc.created_at
        FROM project_capabilities pc
        WHERE NOT EXISTS (
            SELECT 1 FROM project_capability_snapshots pcs
            WHERE pcs.project_id = pc.project_id
              AND pcs.task_type = 'legacy'
              AND pcs.kind = pc.kind
              AND pcs.capability_id = pc.capability_id
        );
        """,
    ),
    (
        "20260608_003_capability_admin_columns",
        """
        -- Per-capability probe + transport columns. ``source_path``
        -- holds the disk path of the skill directory or stdio MCP
        -- entry; the http transport columns are nullable so the same
        -- table can host both transports.
        ALTER TABLE capability_catalog ADD COLUMN source_path TEXT;
        ALTER TABLE capability_catalog ADD COLUMN transport TEXT;
        ALTER TABLE capability_catalog ADD COLUMN command TEXT;
        ALTER TABLE capability_catalog ADD COLUMN args TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE capability_catalog ADD COLUMN url TEXT;
        ALTER TABLE capability_catalog ADD COLUMN bearer_token_env TEXT;
        ALTER TABLE capability_catalog ADD COLUMN headers TEXT NOT NULL DEFAULT '{}';
        """,
    ),
    (
        "20260607_003_dispatcher_locks",
        """
        CREATE TABLE IF NOT EXISTS dispatcher_locks (
            name TEXT PRIMARY KEY,
            holder TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL
        );
        """,
    ),
    (
        "20260607_004_state_uniqueness",
        """
        -- State-machine invariants that used to live only in service
        -- code. Partial unique indexes keep retries and racing writers
        -- from producing duplicate completion/provenance edges.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_intents_project_goal_once
            ON intents(project_id)
            WHERE to_fact_id = 'goal';

        CREATE UNIQUE INDEX IF NOT EXISTS idx_intents_project_fact_once
            ON intents(project_id, to_fact_id)
            WHERE to_fact_id IS NOT NULL AND to_fact_id != 'goal';
        """,
    ),
]


def configure(path: Path) -> None:
    global _db_path
    if _db_path is not None:
        return
    _db_path = path
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Progressive migration: add projects.proxy_id to databases created
        # before proxies were introduced. SQLite has no ADD COLUMN IF NOT
        # EXISTS, so we introspect via PRAGMA table_info.
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "proxy_id" not in cols:
            conn.execute(
                "ALTER TABLE projects ADD COLUMN proxy_id TEXT "
                "REFERENCES proxies(id) ON DELETE SET NULL"
            )
        if "reason_run_id" not in cols:
            conn.execute("ALTER TABLE projects ADD COLUMN reason_run_id TEXT")
        _apply_migrations(conn)


def configured_path() -> Path:
    assert _db_path is not None
    return _db_path


def _apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            sql TEXT NOT NULL,
            error TEXT NOT NULL,
            occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """
    )
    for version, sql in MIGRATIONS:
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (version,),
        ).fetchone()
        if applied is not None:
            continue
        if version == "20260604_005_reason_run_id":
            project_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "reason_run_id" in project_cols:
                conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
                continue
        try:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        except Exception as exc:
            conn.execute(
                "INSERT INTO migration_errors (version, sql, error) VALUES (?, ?, ?)",
                (version, sql, str(exc)),
            )
            raise


def _open_conn() -> sqlite3.Connection:
    assert _db_path is not None
    conn = sqlite3.connect(str(_db_path), timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError as exc:
        lower = str(exc).lower()
        if "file is not a database" not in lower and "disk i/o error" not in lower:
            conn.close()
            raise
        wal_path = Path(f"{_db_path}-wal")
        shm_path = Path(f"{_db_path}-shm")
        LOG.warning(
            "sqlite wal setup failed path=%s error=%s wal_exists=%s shm_exists=%s; falling back to DELETE journal mode",
            _db_path,
            exc,
            wal_path.exists(),
            shm_path.exists(),
        )
        conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def sqlite_status() -> dict[str, Any]:
    """Return operator-facing SQLite status for health/debug commands."""
    path = configured_path()
    with get_conn() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        quick = run_quick_check(conn)
        checkpoint = passive_checkpoint(conn)
        migration_error = conn.execute(
            "SELECT version, error, occurred_at FROM migration_errors ORDER BY id DESC LIMIT 1"
        ).fetchone()
        applied_count = conn.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()["count"]
    status = {
        "journal_mode": journal_mode,
        "busy_timeout_ms": busy_timeout,
        "foreign_keys": bool(foreign_keys),
        "quick_check": quick,
        "wal_checkpoint": checkpoint,
        "applied_migrations": applied_count,
        "migration_error": dict(migration_error) if migration_error is not None else None,
    }
    return {**file_state(path), **status}


def quick_check() -> list[str]:
    """Run SQLite PRAGMA quick_check and return every result row."""
    with get_conn() as conn:
        return run_quick_check(conn)


def integrity_check() -> list[str]:
    """Run SQLite PRAGMA integrity_check and return every result row."""
    with get_conn() as conn:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    return [str(row[0]) for row in rows]


def checkpoint_truncate() -> dict[str, Any]:
    """Run PRAGMA wal_checkpoint(TRUNCATE) and return before/after file state."""
    path = configured_path()
    before = file_state(path)
    with get_conn() as conn:
        result = truncate_checkpoint(conn)
    after = file_state(path)
    return {"path": str(path), "before": before, "checkpoint": result, "after": after}


def diagnostic_error(exc: BaseException) -> str:
    """Render a DB error with the configured SQLite file state."""
    return database_error_detail(configured_path(), exc)


def backup_to(destination: Path) -> Path:
    """Create a consistent online backup of the configured database."""
    destination = destination.expanduser()
    if destination.is_dir():
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        destination = destination / f"cairn-{stamp}.sqlite"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = _thread_conn()
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
    return destination


def _thread_conn() -> sqlite3.Connection:
    assert _db_path is not None
    cached = getattr(_local, "conn", None)
    cached_path = getattr(_local, "path", None)
    if cached is not None and cached_path == _db_path:
        return cached
    if cached is not None:
        try:
            cached.close()
        except Exception:
            pass
    conn = _open_conn()
    _local.conn = conn
    _local.path = _db_path
    return conn


def close_thread_conn() -> None:
    """Close the cached SQLite connection for the current thread."""
    cached = getattr(_local, "conn", None)
    if cached is not None:
        cached.close()
    _local.conn = None
    _local.path = None


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = _thread_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@contextmanager
def with_immediate_tx() -> Generator[sqlite3.Connection, None, None]:
    """Open a connection and acquire a write lock up front.

    SQLite's default deferred transactions acquire the write lock only
    at the first write statement, which can make multi-step writes fail
    late with SQLITE_BUSY. ``BEGIN IMMEDIATE`` grabs the reserved lock
    before the caller runs any read-modify-write sequence.
    """
    conn = _thread_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
