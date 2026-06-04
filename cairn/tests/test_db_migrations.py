from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
