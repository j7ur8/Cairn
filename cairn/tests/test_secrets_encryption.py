"""Tests for the Fernet-encrypted sk storage.

Covers:
  * round-trip encryption (encrypt -> decrypt)
  * empty strings are stored as empty strings (no encryption)
  * placeholder prefix is present on encrypted output
  * decryption of a wrong-key ciphertext raises ``SecretDecryptionError``
  * the on-disk sk column is never plaintext after a write
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class SecretsEncryptionTests(unittest.TestCase):
    def setUp(self) -> None:
        from cairn.server.security import secrets
        secrets._fernet.cache_clear() if hasattr(secrets._fernet, "cache_clear") else None
        # Reset the env to a known value so tests are independent.
        os.environ["CAIRN_JWT_SECRET"] = "test-jwt-secret-do-not-use-in-prod-32bytes"

    def test_round_trip(self) -> None:
        from cairn.server.security.secrets import encrypt_secret, decrypt_secret
        token = encrypt_secret("sk-this-is-a-fake-key-for-testing-only")
        self.assertTrue(token.startswith("enc:v1:"))
        self.assertEqual(decrypt_secret(token), "sk-this-is-a-fake-key-for-testing-only")

    def test_empty_string_round_trip(self) -> None:
        from cairn.server.security.secrets import encrypt_secret, decrypt_secret
        self.assertEqual(encrypt_secret(""), "")
        self.assertEqual(decrypt_secret(""), "")

    def test_placeholder_prefix(self) -> None:
        from cairn.server.security.secrets import encrypt_secret, is_encrypted
        token = encrypt_secret("sk-abc")
        self.assertTrue(is_encrypted(token))
        self.assertFalse(is_encrypted(""))
        self.assertFalse(is_encrypted("plaintext"))

    def test_wrong_key_raises(self) -> None:
        from cairn.server.security.secrets import SecretDecryptionError, decrypt_secret, encrypt_secret
        # Encrypt with key A
        os.environ["CAIRN_JWT_SECRET"] = "key-A-32-bytes-of-fake-material"
        token = encrypt_secret("sk-abc")
        # Switch to key B and try to decrypt
        os.environ["CAIRN_JWT_SECRET"] = "key-B-32-bytes-of-fake-material"
        with self.assertRaises(SecretDecryptionError):
            decrypt_secret(token)

    def test_no_key_set_raises(self) -> None:
        from cairn.server.security import secrets
        # Make sure both env vars are unset for this test.
        os.environ.pop("CAIRN_JWT_SECRET", None)
        os.environ.pop("CAIRN_SECRETS_KEY", None)
        with self.assertRaises(secrets.SecretError):
            secrets.encrypt_secret("sk-abc")


class AiProfileEncryptedStorageTests(unittest.TestCase):
    """End-to-end: write via router, verify ciphertext on disk, read back."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db
        db._db_path = None
        db.configure(Path(self.tmp.name))
        os.environ["CAIRN_JWT_SECRET"] = "test-jwt-secret-do-not-use-in-prod-32bytes"

    def tearDown(self) -> None:
        from cairn.server import db
        db._db_path = None
        os.unlink(self.tmp.name)

    def test_create_writes_ciphertext_not_plaintext(self) -> None:
        from cairn.server.routers.ai_profiles import create_ai_profile, get_ai_profile_secret
        from cairn.server.models import AiProfileCreate

        plaintext = "sk-very-secret-and-must-not-leak-1234"
        created = create_ai_profile(AiProfileCreate(
            name="gpt-encrypted",
            worker_type="codex",
            model="gpt-test",
            api_key_env="OPENAI_API_KEY",
            sk=plaintext,
        ))
        # The model on the read path exposes only sk_set / sk_preview.
        self.assertTrue(created.sk_set)
        self.assertTrue(created.sk_preview.endswith("1234"))

        # The dispatcher secret endpoint returns the plaintext.
        secret = get_ai_profile_secret(created.id)
        self.assertEqual(secret["value"], plaintext)

        # The on-disk column is encrypted, not plaintext.
        with sqlite3.connect(self.tmp.name) as conn:
            row = conn.execute(
                "SELECT sk, sk_ciphertext FROM ai_profiles WHERE id = ?", (created.id,),
            ).fetchone()
        self.assertNotEqual(row[1], "")
        self.assertNotIn(plaintext, row[1])
        self.assertNotIn(plaintext, row[0])

    def test_sync_writes_ciphertext(self) -> None:
        from cairn.server.routers.ai_profiles import sync_ai_profiles, get_ai_profile_secret
        from cairn.server.models import AiProfileSyncRequest, AiProfileSyncWorker

        plaintext = "sk-from-dispatch-yaml-must-encrypt"
        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(
                name="codex", worker_type="codex", model="gpt-5",
                api_key_env="OPENAI_API_KEY", models=["gpt-5"],
                sk=plaintext,
            ),
        ])
        sync_ai_profiles(body)
        # The sk is queryable via the dispatcher secret endpoint.
        secret = get_ai_profile_secret("ai_seed_codex")
        self.assertEqual(secret["value"], plaintext)
        with sqlite3.connect(self.tmp.name) as conn:
            row = conn.execute(
                "SELECT sk, sk_ciphertext FROM ai_profiles WHERE id = ?", ("ai_seed_codex",),
            ).fetchone()
        self.assertNotEqual(row[1], "")
        self.assertNotIn(plaintext, row[1])


if __name__ == "__main__":
    unittest.main()
