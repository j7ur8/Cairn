from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import TempYamlConfig, reset_postgres_db


class AiProfileSecretTests(unittest.TestCase):
    def setUp(self) -> None:
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        self.yaml.__exit__(None, None, None)

    def test_create_with_sk_masks_value_in_listing(self) -> None:
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate
        from cairn.server.routers import ai_profiles as r

        created = r.create_ai_profile(AiProfileCreate(
            name="gpt-test",
            worker_type="codex",
            model="gpt-5.4",
            api_key_env="OPENAI_API_KEY",
            sk="sk-1234567890abcd",
        ))
        self.assertTrue(created.sk_set)
        self.assertEqual(created.sk_preview, "***abcd")
        self.assertNotIn("sk", created.model_dump(mode="json"))

        listed = r.list_ai_profiles()
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0].sk_set)
        self.assertEqual(listed[0].sk_preview, "***abcd")

    def test_secret_endpoint_returns_raw_yaml_value(self) -> None:
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate
        from cairn.server.routers import ai_profiles as r

        created = r.create_ai_profile(AiProfileCreate(
            name="raw",
            worker_type="codex",
            model="gpt-5.4",
            api_key_env="OPENAI_API_KEY",
            sk="sk-secret-9999",
        ))
        self.assertEqual(r.get_ai_profile_secret(created.id)["value"], "sk-secret-9999")

    def test_secret_endpoint_returns_literal_yaml_reference(self) -> None:
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate
        from cairn.server.routers import ai_profiles as r

        created = r.create_ai_profile(AiProfileCreate(
            name="literal",
            worker_type="codex",
            model="gpt-5.4",
            api_key_env="OPENAI_API_KEY",
            sk="sk-direct-yaml-value",
        ))
        self.assertEqual(r.get_ai_profile_secret(created.id)["value"], "sk-direct-yaml-value")

    def test_put_empty_string_is_rejected(self) -> None:
        from fastapi import HTTPException
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate, AiProfileUpdate
        from cairn.server.routers import ai_profiles as r

        created = r.create_ai_profile(AiProfileCreate(
            name="clear",
            worker_type="codex",
            model="gpt-5.4",
            api_key_env="OPENAI_API_KEY",
            sk="sk-temp-2222",
        ))
        with self.assertRaises(HTTPException) as ctx:
            r.update_ai_profile(created.id, AiProfileUpdate(sk=""))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_put_omitted_sk_preserves_existing(self) -> None:
        from cairn.server.models_pkg.ai_profiles import AiProfileCreate, AiProfileUpdate
        from cairn.server.routers import ai_profiles as r

        created = r.create_ai_profile(AiProfileCreate(
            name="keep",
            worker_type="codex",
            model="gpt-5.4",
            api_key_env="OPENAI_API_KEY",
            sk="sk-original-1111",
        ))
        updated = r.update_ai_profile(created.id, AiProfileUpdate(name="keep-renamed"))
        self.assertTrue(updated.sk_set)
        self.assertEqual(r.get_ai_profile_secret(created.id)["value"], "sk-original-1111")


if __name__ == "__main__":
    unittest.main()
