from __future__ import annotations

import os
os.environ.setdefault('CAIRN_JWT_SECRET', 'test-jwt-secret-do-not-use-in-prod-32bytes')
os.environ.setdefault('CAIRN_SECRETS_KEY', 'test-jwt-secret-do-not-use-in-prod-32bytes')

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class DbMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db

        db._db_path = None
        db.configure(Path(self.tmp.name))
        self.db = db

    def tearDown(self) -> None:
        self.db._db_path = None
        os.unlink(self.tmp.name)

    def test_schema_migrations_records_core_indexes(self) -> None:
        with self.db.get_conn() as conn:
            rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        versions = {row["version"] for row in rows}
        self.assertIn("20260604_001_core_indexes", versions)
        self.assertIn("20260604_004_reason_state", versions)
        self.assertIn("20260604_005_reason_run_id", versions)

    def test_core_indexes_exist(self) -> None:
        expected = {
            "idx_facts_project_id",
            "idx_hints_project_id",
            "idx_intents_project_open_worker",
            "idx_intents_project_to_fact",
            "idx_intent_sources_project_fact",
            "idx_project_capabilities_project_kind",
            "idx_replay_steps_run_status",
            "idx_project_reason_state_retry",
        }
        with self.db.get_conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        names = {row["name"] for row in rows}
        self.assertTrue(expected.issubset(names), expected - names)


class LegacySeededProfilePruneMigrationTests(unittest.TestCase):
    """The 20260605_008 migration removes the obsolete ``ai_seed_codex_gpt-5_4`` row.

    The migration must run on databases that already have the stale row
    (i.e. before any dispatcher sync) and be idempotent on databases that
    do not. We exercise both shapes.
    """

    def _reconfigure_with_seeded_row(self) -> None:
        """Re-create the DB and plant the legacy seeded row before re-applying the migration.

        Strategy: run ``configure`` once to bring up the full schema, then
        plant the legacy row, then scrub the migration record and re-run
        ``configure`` so the DELETE statements re-execute against the
        planted row.
        """
        from cairn.server import db
        db._db_path = None
        db.configure(Path(self.tmp.name))
        with db.get_conn() as conn:
            now = "2026-06-05T00:00:00Z"
            conn.execute(
                """
                INSERT INTO ai_profiles (
                    id, name, worker_type, provider, base_url,
                    model, api_key_env, available, detail,
                    healthcheck_timeout, seeded_from_worker,
                    created_at, updated_at
                ) VALUES (?, ?, 'codex', '', '', 'gpt-5.4', 'OPENAI_API_KEY', 1, '', 1.0, ?, ?, ?)
                """,
                ("ai_seed_codex_gpt-5_4", "codex:gpt-5.4", "codex:gpt-5.4", now, now),
            )
            conn.execute(
                "INSERT INTO ai_profile_models (profile_id, model, updated_at) VALUES (?, ?, ?)",
                ("ai_seed_codex_gpt-5_4", "gpt-5.4", now),
            )
            # Make the migration look unapplied so configure() re-runs it.
            conn.execute(
                "DELETE FROM schema_migrations WHERE version = ?",
                ("20260605_008_prune_legacy_seeded_ai_profile",),
            )
            conn.commit()
        db._db_path = None
        db.configure(Path(self.tmp.name))
        self.db = db

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()

    def tearDown(self) -> None:
        if self.db is not None:
            self.db._db_path = None
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_migration_prunes_legacy_seeded_row(self) -> None:
        self.db = None  # populated by helper
        self._reconfigure_with_seeded_row()
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM ai_profiles WHERE id = ? OR seeded_from_worker = ?",
                ("ai_seed_codex_gpt-5_4", "codex:gpt-5.4"),
            ).fetchone()
            self.assertIsNone(row)
            model_rows = conn.execute(
                "SELECT model FROM ai_profile_models WHERE profile_id = ?",
                ("ai_seed_codex_gpt-5_4",),
            ).fetchall()
            self.assertEqual(model_rows, [])
            version_row = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                ("20260605_008_prune_legacy_seeded_ai_profile",),
            ).fetchone()
            self.assertIsNotNone(version_row)

    def test_migration_is_idempotent_when_row_absent(self) -> None:
        from cairn.server import db
        db._db_path = None
        db.configure(Path(self.tmp.name))
        self.db = db
        # Pre-seed only the supported rows; the legacy row was never present.
        with self.db.get_conn() as conn:
            now = "2026-06-05T00:00:00Z"
            conn.execute(
                """
                INSERT INTO ai_profiles (
                    id, name, worker_type, provider, base_url,
                    model, api_key_env, available, detail,
                    healthcheck_timeout, seeded_from_worker,
                    created_at, updated_at
                ) VALUES (?, ?, 'codex', '', '', 'gpt-5.4', 'OPENAI_API_KEY', 1, '', 1.0, ?, ?, ?)
                """,
                ("ai_seed_codex", "codex", "codex", now, now),
            )
            conn.commit()
        # Re-running configure must not raise even though the legacy row
        # does not exist.
        self.db._db_path = None
        self.db.configure(Path(self.tmp.name))
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM ai_profiles WHERE id = ?",
                ("ai_seed_codex",),
            ).fetchone()
            self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
