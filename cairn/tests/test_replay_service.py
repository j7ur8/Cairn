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

    def test_extract_route_preserves_multiple_producer_error(self) -> None:
        from unittest.mock import patch

        from cairn.server.application.replay import route_extractor
        from cairn.server.domain.errors import ConflictError

        class FakeReplayRepository:
            def __init__(self, conn):
                pass

            def route_graph_for_facts(self, project_id, seed_fact_ids):
                intent_a = {"id": "intent_a", "to_fact_id": "fact_a"}
                intent_b = {"id": "intent_b", "to_fact_id": "fact_a"}
                return (
                    {"intent_a": intent_a, "intent_b": intent_b},
                    {"intent_a": ["origin"], "intent_b": ["origin"]},
                    {"fact_a": [intent_a, intent_b]},
                )

        with patch.object(route_extractor, "ReplayRepository", FakeReplayRepository):
            with self.assertRaisesRegex(ConflictError, "Fact fact_a has multiple producing intents"):
                route_extractor.extract_replay_route(object(), "proj_replay", ["fact_a"])


if __name__ == "__main__":
    unittest.main()
