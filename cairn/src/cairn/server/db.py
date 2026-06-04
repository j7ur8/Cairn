from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DEFAULT_DB = Path.home() / ".local" / "share" / "cairn" / "cairn.db"
SQLITE_TIMEOUT_SECONDS = 5.0
SQLITE_BUSY_TIMEOUT_MS = 5000

_db_path: Path | None = None

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

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
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
        _apply_migrations(conn)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
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
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    assert _db_path is not None
    conn = sqlite3.connect(str(_db_path), timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
