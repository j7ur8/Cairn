from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class MockScriptCompileTests(unittest.TestCase):
    def test_embedded_script_compiles(self) -> None:
        from cairn.dispatcher.workers.adapters import mock

        # If this raises, the import would already have failed; assert anyway so
        # the guarantee is pinned and visible as a test.
        compile(mock._SCRIPT, "<mock-worker-script>", "exec")

    def test_compile_helper_rejects_bad_syntax(self) -> None:
        from cairn.dispatcher.workers.adapters import mock

        original = mock._SCRIPT
        try:
            mock._SCRIPT = "def broken(:\n    pass"
            with self.assertRaises(RuntimeError) as ctx:
                mock._compile_script()
            self.assertIn("syntax error", str(ctx.exception))
        finally:
            mock._SCRIPT = original

    def test_explore_execute_fact_uses_sentinel_output(self) -> None:
        from cairn.dispatcher.workers.adapters import mock
        from cairn.shared.config.mock_behavior import resolve_mock_behavior

        behavior = resolve_mock_behavior("mock", {})
        behavior["explore_execute"]["delay"] = {"min": 0, "max": 0}
        result = subprocess.run(
            [
                "python3",
                "-c",
                mock._SCRIPT,
                json.dumps(behavior),
                json.dumps({"phase": "explore_execute", "intent_id": "intent_1"}),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            result.stdout.strip(),
            "32173462130721312360912mock fact for intent_132173462130721312360912",
        )

    def test_reason_intent_uses_intents_marker_output(self) -> None:
        from cairn.dispatcher.contracts import parse_reason_output, validate_reason_payload
        from cairn.dispatcher.workers.adapters import mock
        from cairn.shared.config.mock_behavior import resolve_mock_behavior

        behavior = resolve_mock_behavior("mock", {})
        behavior["reason"]["delay"] = {"min": 0, "max": 0}
        behavior["reason"]["outcomes"] = {
            "complete": 0.0,
            "intent": 1.0,
            "noop": 0.0,
            "rejected": 0.0,
            "invalid_json": 0.0,
            "invalid_payload": 0.0,
            "command_fail": 0.0,
        }
        result = subprocess.run(
            [
                "python3",
                "-c",
                mock._SCRIPT,
                json.dumps(behavior),
                json.dumps(
                    {
                        "phase": "reason",
                        "fact_ids": ["f001"],
                        "open_intents": [],
                        "max_intents": 1,
                    }
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertTrue(result.stdout.startswith("84913462130721312360912"))
        self.assertTrue(result.stdout.strip().endswith("84913462130721312360912"))
        payload = parse_reason_output(result.stdout)
        kind, data = validate_reason_payload(payload, open_intents_empty=True, max_intents=1)
        self.assertEqual(kind, "intents")
        assert isinstance(data, list)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
