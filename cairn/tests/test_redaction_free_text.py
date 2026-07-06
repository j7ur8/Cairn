from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class RedactionFreeTextTests(unittest.TestCase):
    def test_free_text_sk_token_is_redacted(self) -> None:
        text = "model replied with sk-abcdefghijklmnopqrstuvwxyz123456 and more"
        for module in (
            "cairn.dispatcher.observability.redaction",
            "cairn.server.observability.redaction",
        ):
            with self.subTest(module=module):
                import importlib

                redact_content = importlib.import_module(module).redact_content
                redacted, changed = redact_content(text, [])
                self.assertTrue(changed)
                self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", redacted)
                self.assertIn("[REDACTED]", redacted)

    def test_large_input_skips_regex_redaction(self) -> None:
        from cairn.dispatcher.observability import redaction

        text = "xx"
        with patch.object(redaction, "MAX_REDACT_INPUT_BYTES", 1):
            out, changed = redaction.redact_content(text, [r"x+"])
        self.assertFalse(changed)
        self.assertEqual(out, text)


if __name__ == "__main__":
    unittest.main()
