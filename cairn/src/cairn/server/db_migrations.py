from __future__ import annotations

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
    (
        "20260608_004_mcp_required_skill_ids",
        """
        -- One-to-many binding from MCP to skills the agent must load
        -- alongside the MCP. Mirrors the skill.requires_ids column: when
        -- a project task picks MCP X, the dispatcher auto-injects each
        -- skill in X.required_skill_ids with project_capability_snapshots
        -- .source = 'required'. Empty default keeps existing rows valid.
        ALTER TABLE capability_catalog ADD COLUMN required_skill_ids TEXT NOT NULL DEFAULT '[]';
        """,
    ),
    (
        "20260608_005_capability_routing_metadata",
        """
        -- Dynamic routing metadata for capability prompt injection.
        -- System code renders these declarations generically instead
        -- of hardcoding business-specific MCP/skill usage rules.
        ALTER TABLE capability_catalog ADD COLUMN use_when TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE capability_catalog ADD COLUMN activation_hint TEXT NOT NULL DEFAULT '';
        ALTER TABLE capability_catalog ADD COLUMN preferred_mcp_ids TEXT NOT NULL DEFAULT '[]';
        """,
    ),
    (
        "20260609_001_role_default_skill_ids",
        """
        -- Roles can declare skills that should be auto-loaded when
        -- the role is selected. Stored as JSON for the same catalog
        -- sync shape used by capability dependency lists.
        ALTER TABLE role_catalog ADD COLUMN default_skill_ids TEXT NOT NULL DEFAULT '[]';
        """,
    ),
    (
        "20260609_001_ai_profile_check_requests",
        """
        CREATE TABLE IF NOT EXISTS ai_profile_check_requests (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES ai_profiles(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
            requested_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            requested_by TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_ai_profile_check_requests_status_requested
            ON ai_profile_check_requests(status, requested_at);
        """,
    ),
]
