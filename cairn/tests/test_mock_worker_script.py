from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
