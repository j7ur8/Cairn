"""Smoke test: AI profile CRUD + project selection round-trip.

Exercises the SQLite layer end to end without going through the HTTP
client (httpx is not available in this venv).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class AiProfileFlowTests(unittest.TestCase):
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

    def _create_project(self, **kwargs):
        with self.db.get_conn() as conn:
            from cairn.server.routers.projects import next_project_id
            pid = next_project_id(conn)
            now = "2026-06-04T00:00:00Z"
            conn.execute(
                "INSERT INTO projects (id, title, status, created_at) VALUES (?, ?, 'active', ?)",
                (pid, kwargs.get("title", "P"), now),
            )
            conn.commit()
        return pid

    def test_crud(self) -> None:
        from cairn.server.routers.ai_profiles import (
            create_ai_profile, list_ai_profiles, get_ai_profile,
            update_ai_profile, delete_ai_profile,
        )
        from cairn.server.models import AiProfileCreate, AiProfileUpdate

        created = create_ai_profile(AiProfileCreate(
            name="gpt-deepseek",
            worker_type="codex",
            model="deepseek-coder",
            api_key_env="DEEPSEEK_KEY",
        ))
        self.assertTrue(created.id.startswith("ai_"))
        self.assertEqual(created.worker_type, "codex")
        self.assertEqual(created.model, "deepseek-coder")

        self.assertEqual(len(list_ai_profiles()), 1)

        fetched = get_ai_profile(created.id)
        self.assertEqual(fetched.id, created.id)

        updated = update_ai_profile(
            created.id,
            AiProfileUpdate(model="deepseek-v3", base_url="https://api.example/v1"),
        )
        self.assertEqual(updated.model, "deepseek-v3")
        self.assertEqual(updated.base_url, "https://api.example/v1")

        delete_ai_profile(created.id)
        self.assertEqual(len(list_ai_profiles()), 0)

    def test_persist_project_selection_round_trip(self) -> None:
        from cairn.server.routers.ai_profiles import (
            create_ai_profile, persist_project_ai_selection,
            get_project_ai_profiles,
        )
        from cairn.server.models import AiProfileCreate, AiProfileSelection

        a = create_ai_profile(AiProfileCreate(
            name="primary-1", worker_type="codex", model="m1", api_key_env="K1",
        ))
        b = create_ai_profile(AiProfileCreate(
            name="fallback-1", worker_type="codex", model="m2", api_key_env="K2",
        ))
        c = create_ai_profile(AiProfileCreate(
            name="fallback-2", worker_type="claudecode", model="m3", api_key_env="K3",
        ))

        pid = self._create_project(title="P1")
        with self.db.get_conn() as conn:
            persist_project_ai_selection(
                conn, pid,
                AiProfileSelection(primary_profile_id=a.id, fallback_profile_ids=[b.id, c.id]),
                "2026-06-04T00:00:00Z",
            )
            conn.commit()

        result = get_project_ai_profiles(pid)
        self.assertEqual(result.selection.primary_profile_id, a.id)
        self.assertEqual(result.selection.fallback_profile_ids, [b.id, c.id])
        self.assertEqual(len(result.snapshots), 3)
        self.assertEqual(result.unavailable_profile_ids, [])

        primary_snapshot = next(s for s in result.snapshots if s.role == "primary")
        self.assertEqual(primary_snapshot.snapshot_model, "m1")
        self.assertEqual(primary_snapshot.snapshot_worker_type, "codex")
        self.assertEqual(primary_snapshot.snapshot_api_key_env, "K1")

    def test_missing_profile_rejected(self) -> None:
        from cairn.server.routers.ai_profiles import persist_project_ai_selection
        from cairn.server.models import AiProfileSelection

        pid = self._create_project(title="P2")
        with self.db.get_conn() as conn:
            with self.assertRaises(Exception) as ctx:
                persist_project_ai_selection(
                    conn, pid,
                    AiProfileSelection(primary_profile_id="ai_doesnotexist", fallback_profile_ids=[]),
                    "2026-06-04T00:00:00Z",
                )
        self.assertIn("not found", str(ctx.exception.detail))

    def test_unavailable_profile_rejected(self) -> None:
        from cairn.server.routers.ai_profiles import (
            create_ai_profile, persist_project_ai_selection,
            update_ai_profile,
        )
        from cairn.server.models import (
            AiProfileCreate, AiProfileUpdate, AiProfileSelection,
        )

        a = create_ai_profile(AiProfileCreate(
            name="p", worker_type="codex", model="m", api_key_env="K",
        ))
        update_ai_profile(a.id, AiProfileUpdate(available=False))

        pid = self._create_project(title="P3")
        with self.db.get_conn() as conn:
            with self.assertRaises(Exception) as ctx:
                persist_project_ai_selection(
                    conn, pid,
                    AiProfileSelection(primary_profile_id=a.id, fallback_profile_ids=[]),
                    "2026-06-04T00:00:00Z",
                )
        self.assertIn("unavailable", str(ctx.exception.detail))

    def test_delete_profile_preserves_snapshots(self) -> None:
        from cairn.server.routers.ai_profiles import (
            create_ai_profile, persist_project_ai_selection,
            get_project_ai_profiles, delete_ai_profile,
        )
        from cairn.server.models import AiProfileCreate, AiProfileSelection

        a = create_ai_profile(AiProfileCreate(
            name="to-delete", worker_type="codex", model="m", api_key_env="K",
        ))
        pid = self._create_project(title="P4")
        with self.db.get_conn() as conn:
            persist_project_ai_selection(
                conn, pid,
                AiProfileSelection(primary_profile_id=a.id, fallback_profile_ids=[]),
                "2026-06-04T00:00:00Z",
            )
            conn.commit()

        delete_ai_profile(a.id)
        result = get_project_ai_profiles(pid)
        # snapshot preserved, marked unavailable
        self.assertEqual(len(result.snapshots), 1)
        self.assertIn(a.id, result.unavailable_profile_ids)

    def test_primary_in_fallback_stripped(self) -> None:
        from cairn.server.routers.ai_profiles import (
            create_ai_profile, persist_project_ai_selection,
            get_project_ai_profiles,
        )
        from cairn.server.models import AiProfileCreate, AiProfileSelection

        a = create_ai_profile(AiProfileCreate(
            name="dup", worker_type="codex", model="m", api_key_env="K",
        ))
        pid = self._create_project(title="P5")
        with self.db.get_conn() as conn:
            persist_project_ai_selection(
                conn, pid,
                AiProfileSelection(primary_profile_id=a.id, fallback_profile_ids=[a.id]),
                "2026-06-04T00:00:00Z",
            )
            conn.commit()
        result = get_project_ai_profiles(pid)
        self.assertEqual(result.selection.primary_profile_id, a.id)
        self.assertNotIn(a.id, result.selection.fallback_profile_ids)
        self.assertEqual(
            sum(1 for s in result.snapshots if s.role == "primary"), 1,
        )

    def test_no_selection_returns_empty(self) -> None:
        from cairn.server.routers.ai_profiles import get_project_ai_profiles

        pid = self._create_project(title="P-empty")
        result = get_project_ai_profiles(pid)
        self.assertEqual(result.selection.primary_profile_id, None)
        self.assertEqual(result.selection.fallback_profile_ids, [])
        self.assertEqual(result.snapshots, [])
        self.assertEqual(result.unavailable_profile_ids, [])


if __name__ == "__main__":
    unittest.main()
