from __future__ import annotations

import unittest
from copy import deepcopy

from helpers import TempYamlConfig


class ReplayServiceTests(unittest.TestCase):
    def test_rewrite_attachment_refs_uses_configured_worker_root(self) -> None:
        with TempYamlConfig() as template:
            dispatch = deepcopy(template.dispatch)
        dispatch["server"]["paths"]["worker_attachments_root"] = "/workspace/inputs"

        with TempYamlConfig(dispatch=dispatch):
            from cairn.server.application.replay.attachments import rewrite_attachment_refs

            text = "Evidence is in /workspace/inputs/proj_src/payload.txt"
            rewritten = rewrite_attachment_refs(text, "proj_src", "proj_dst")

        self.assertEqual(rewritten, "Evidence is in /workspace/inputs/proj_dst/payload.txt")


if __name__ == "__main__":
    unittest.main()
