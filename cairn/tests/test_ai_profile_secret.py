"""Tests for the per-profile ``sk`` secret key.

Covers the full surface added for the form: the new column, the masked
read shape, the write-only input semantics, the dispatcher-facing
secret endpoint, and the sync-reuse path that pushes the resolved
token from ``dispatch.yaml`` into the DB at sync time.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class AiProfileSecretTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db
        db._db_path = None
        db.configure(Path(self.tmp.name))
        self.db = db
        from cairn.server.routers import ai_profiles as r
        from cairn.server.models import (
            AiProfileCreate, AiProfileUpdate, AiProfileSyncRequest, AiProfileSyncWorker,
        )
        self.r = r
        self.AiProfileCreate = AiProfileCreate
        self.AiProfileUpdate = AiProfileUpdate
        self.AiProfileSyncRequest = AiProfileSyncRequest
        self.AiProfileSyncWorker = AiProfileSyncWorker

    def tearDown(self) -> None:
        self.db._db_path = None
        os.unlink(self.tmp.name)

    # ---- create / read round-trip ----

    def test_create_with_sk_masks_value_in_listing(self) -> None:
        created = self.r.create_ai_profile(self.AiProfileCreate(
            name="gpt-test", worker_type="codex", model="gpt-5.4",
            api_key_env="OPENAI_API_KEY", sk="sk-1234567890abcd",
        ))
        self.assertTrue(created.sk_set)
        self.assertEqual(created.sk_preview, "***abcd")  # last 4 chars
        # Raw sk must NEVER appear in the response shape.
        dump = created.model_dump(mode="json")
        self.assertNotIn("sk", dump)
        self.assertTrue(dump["sk_set"])
        self.assertEqual(dump["sk_preview"], "***abcd")

        listed = self.r.list_ai_profiles()
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0].sk_set)
        self.assertEqual(listed[0].sk_preview, "***abcd")
        self.assertNotIn("sk", listed[0].model_dump(mode="json"))

    def test_create_with_empty_sk_keeps_unset(self) -> None:
        created = self.r.create_ai_profile(self.AiProfileCreate(
            name="plain", worker_type="claudecode", model="claude-sonnet-4.5",
            api_key_env="ANTHROPIC_AUTH_TOKEN", sk="",
        ))
        self.assertFalse(created.sk_set)
        self.assertEqual(created.sk_preview, "")

    # ---- dispatcher-facing secret endpoint ----

    def test_secret_endpoint_returns_raw_value(self) -> None:
        created = self.r.create_ai_profile(self.AiProfileCreate(
            name="raw", worker_type="codex", model="gpt-5.4",
            api_key_env="OPENAI_API_KEY", sk="sk-secret-9999",
        ))
        result = self.r.get_ai_profile_secret(created.id)
        self.assertEqual(result["value"], "sk-secret-9999")

    def test_secret_endpoint_returns_none_for_empty_sk(self) -> None:
        created = self.r.create_ai_profile(self.AiProfileCreate(
            name="empty", worker_type="codex", model="gpt-5.4",
            api_key_env="OPENAI_API_KEY",
        ))
        result = self.r.get_ai_profile_secret(created.id)
        self.assertIsNone(result["value"])

    def test_secret_endpoint_404_for_unknown(self) -> None:
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.r.get_ai_profile_secret("ai_does_not_exist")
        self.assertEqual(ctx.exception.status_code, 404)

    # ---- PUT semantics ----

    def test_put_untouched_sk_preserves_existing(self) -> None:
        created = self.r.create_ai_profile(self.AiProfileCreate(
            name="keep", worker_type="codex", model="gpt-5.4",
            api_key_env="OPENAI_API_KEY", sk="sk-original-1111",
        ))
        # PUT with no ``sk`` key (None) — must not wipe the stored value.
        updated = self.r.update_ai_profile(
            created.id,
            self.AiProfileUpdate(name="keep-renamed"),
        )
        self.assertTrue(updated.sk_set)
        self.assertEqual(updated.sk_preview, "***1111")
        # The actual DB value is still there.
        result = self.r.get_ai_profile_secret(created.id)
        self.assertEqual(result["value"], "sk-original-1111")

    def test_put_empty_string_clears_stored_sk(self) -> None:
        created = self.r.create_ai_profile(self.AiProfileCreate(
            name="clear", worker_type="codex", model="gpt-5.4",
            api_key_env="OPENAI_API_KEY", sk="sk-temp-2222",
        ))
        updated = self.r.update_ai_profile(
            created.id,
            self.AiProfileUpdate(sk=""),
        )
        self.assertFalse(updated.sk_set)
        self.assertEqual(updated.sk_preview, "")
        result = self.r.get_ai_profile_secret(created.id)
        self.assertIsNone(result["value"])

    def test_put_non_empty_replaces_stored_sk(self) -> None:
        created = self.r.create_ai_profile(self.AiProfileCreate(
            name="replace", worker_type="codex", model="gpt-5.4",
            api_key_env="OPENAI_API_KEY", sk="sk-old-3333",
        ))
        updated = self.r.update_ai_profile(
            created.id,
            self.AiProfileUpdate(sk="sk-new-4444"),
        )
        self.assertTrue(updated.sk_set)
        self.assertEqual(updated.sk_preview, "***4444")
        result = self.r.get_ai_profile_secret(created.id)
        self.assertEqual(result["value"], "sk-new-4444")

    # ---- sync reuse ----

    def test_sync_inserts_with_sk(self) -> None:
        req = self.AiProfileSyncRequest(workers=[
            self.AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5.4",
                api_key_env="OPENAI_API_KEY", sk="sk-from-yaml-5555",
            ),
        ])
        self.r.sync_ai_profiles(req)
        # The seeded profile is keyed deterministically by worker name.
        result = self.r.get_ai_profile_secret("ai_seed_codex")
        self.assertEqual(result["value"], "sk-from-yaml-5555")

    def test_sync_update_with_empty_sk_preserves_existing(self) -> None:
        # First sync populates the sk.
        self.r.sync_ai_profiles(self.AiProfileSyncRequest(workers=[
            self.AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5.4",
                api_key_env="OPENAI_API_KEY", sk="sk-first-6666",
            ),
        ]))
        # Second sync without sk — must not clobber the stored value.
        self.r.sync_ai_profiles(self.AiProfileSyncRequest(workers=[
            self.AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5.4",
                api_key_env="OPENAI_API_KEY", sk=None,
            ),
        ]))
        result = self.r.get_ai_profile_secret("ai_seed_codex")
        self.assertEqual(result["value"], "sk-first-6666")

    def test_sync_update_with_new_sk_replaces(self) -> None:
        self.r.sync_ai_profiles(self.AiProfileSyncRequest(workers=[
            self.AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5.4",
                api_key_env="OPENAI_API_KEY", sk="sk-old-7777",
            ),
        ]))
        # Re-deploy: sync re-runs with a new token.
        self.r.sync_ai_profiles(self.AiProfileSyncRequest(workers=[
            self.AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5.4",
                api_key_env="OPENAI_API_KEY", sk="sk-rotated-8888",
            ),
        ]))
        result = self.r.get_ai_profile_secret("ai_seed_codex")
        self.assertEqual(result["value"], "sk-rotated-8888")

    def test_sync_with_typed_form_sk_preserves_user_value(self) -> None:
        # Operator types a key into the form on a seeded profile.
        seeded = self.r.sync_ai_profiles(self.AiProfileSyncRequest(workers=[
            self.AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5.4",
                api_key_env="OPENAI_API_KEY", sk="sk-from-yaml-9999",
            ),
        ]))
        profile_id = next(p.id for p in seeded)
        # The operator edits the profile in the form to override the sk.
        self.r.update_ai_profile(profile_id, self.AiProfileUpdate(sk="sk-form-typed-0000"))
        # A subsequent dispatcher sync that ran without the env var must
        # NOT wipe the form-typed value.
        self.r.sync_ai_profiles(self.AiProfileSyncRequest(workers=[
            self.AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5.4",
                api_key_env="OPENAI_API_KEY", sk=None,
            ),
        ]))
        result = self.r.get_ai_profile_secret(profile_id)
        self.assertEqual(result["value"], "sk-form-typed-0000")


if __name__ == "__main__":
    unittest.main()
