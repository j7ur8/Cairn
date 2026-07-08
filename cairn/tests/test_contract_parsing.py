from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class ContractParsingTests(unittest.TestCase):
    def test_default_reason_prompt_uses_plain_intent_contract(self) -> None:
        prompt = (_REPO / "cairn/src/cairn/dispatcher/prompts/reason/common/reason.md").read_text()

        forbidden_terms = [
            "priority_score",
            "intent_kind",
            "score_reason",
            "branch_key",
            "branch_depth",
            "expected_value",
            "area.family.method",
        ]
        for term in forbidden_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, prompt.lower())
        self.assertIn('"from": ["f001"], "description": "..."', prompt)

    def test_parse_sentinel_fact_output_parses_sentinel_fact_text(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        stdout = (
            '{"type":"thread.started","thread_id":"t1"}\n'
            '32173462130721312360912sentinel fact32173462130721312360912\n'
            '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
        )

        self.assertEqual(parse_sentinel_fact_output(stdout), "sentinel fact")

    def test_parse_sentinel_fact_output_parses_multiline_sentinel_fact_text(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        stdout = (
            "32173462130721312360912"
            "line one\n\n## Heading\n- item"
            "32173462130721312360912"
        )

        self.assertEqual(parse_sentinel_fact_output(stdout), "line one\n\n## Heading\n- item")

    def test_parse_sentinel_fact_output_rejects_missing_sentinel(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "no sentinel fact found"):
            parse_sentinel_fact_output("plain error without markers")

    def test_parse_sentinel_fact_output_rejects_empty_sentinel_fact(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            parse_sentinel_fact_output(
                "32173462130721312360912   \n  32173462130721312360912"
            )

    def test_parse_sentinel_fact_output_rejects_multiple_sentinel_facts(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "multiple sentinel facts"):
            parse_sentinel_fact_output(
                "32173462130721312360912one32173462130721312360912"
                "32173462130721312360912two32173462130721312360912"
            )

    def test_parse_sentinel_fact_output_rejects_json_inside_sentinel(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "plain text, not JSON"):
            parse_sentinel_fact_output(
                '32173462130721312360912{"accepted":true,"data":{"description":"old"}}32173462130721312360912'
            )

    def test_parse_sentinel_fact_output_rejects_bare_json_object_text(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "plain text, not JSON"):
            parse_sentinel_fact_output(
                "32173462130721312360912\n"
                '{"description":"json-looking text"}'
                "\n32173462130721312360912"
            )

    def test_json_parser_still_handles_agent_message_protocol_json(self) -> None:
        from cairn.dispatcher.contracts import parse_json_output, validate_explore_payload

        stdout = (
            '{"type":"thread.started","thread_id":"t1"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message",'
            '"text":"{\\"accepted\\":true,\\"data\\":{\\"description\\":\\"codex fact\\"}}"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
        )

        payload = parse_json_output(stdout)

        self.assertEqual(payload["accepted"], True)
        self.assertEqual(validate_explore_payload(payload), ("fact", "codex fact"))

    def test_codex_event_without_protocol_payload_still_fails(self) -> None:
        from cairn.dispatcher.contracts import parse_json_output

        stdout = '{"type":"turn.started"}\n{"type":"turn.completed"}\n'

        with self.assertRaisesRegex(ValueError, "no JSON object found"):
            parse_json_output(stdout)

    def test_parse_reason_output_parses_complete_marker_payload(self) -> None:
        from cairn.dispatcher.contracts import parse_reason_output, validate_reason_payload

        stdout = (
            '32173462130721312360912{"accepted":true,"data":{"complete":'
            '{"from":["f001"],"description":"done"}}}32173462130721312360912'
        )

        payload = parse_reason_output(stdout)
        self.assertEqual(
            validate_reason_payload(payload, open_intents_empty=True, max_intents=2),
            ("complete", {"from": ["f001"], "description": "done"}),
        )

    def test_parse_reason_output_parses_intents_marker_payload(self) -> None:
        from cairn.dispatcher.contracts import parse_reason_output, validate_reason_payload

        stdout = (
            '84913462130721312360912{"accepted":true,"data":{"intents":'
            '[{"from":["f001"],"description":"next"}]}}84913462130721312360912'
        )

        payload = parse_reason_output(stdout)
        self.assertEqual(
            validate_reason_payload(payload, open_intents_empty=True, max_intents=2),
            ("intents", [{"from": ["f001"], "description": "next"}]),
        )

    def test_parse_reason_output_parses_noop_marker_payload(self) -> None:
        from cairn.dispatcher.contracts import parse_reason_output, validate_reason_payload

        stdout = '00003462130721312360912{"accepted":true,"data":{}}00003462130721312360912'

        payload = parse_reason_output(stdout)
        self.assertEqual(
            validate_reason_payload(payload, open_intents_empty=False, max_intents=2),
            ("noop", None),
        )

    def test_parse_reason_output_rejects_marker_payload_mismatch(self) -> None:
        from cairn.dispatcher.contracts import parse_reason_output

        stdout = (
            '32173462130721312360912{"accepted":true,"data":{"intents":'
            '[{"from":["f001"],"description":"next"}]}}32173462130721312360912'
        )

        with self.assertRaisesRegex(ValueError, "complete sentinel requires"):
            parse_reason_output(stdout)

    def test_parse_reason_output_falls_back_to_unwrapped_json(self) -> None:
        from cairn.dispatcher.contracts import parse_reason_output, validate_reason_payload

        payload = parse_reason_output(
            '{"accepted":true,"data":{"intents":[{"from":["f001"],"description":"legacy"}]}}'
        )

        self.assertEqual(
            validate_reason_payload(payload, open_intents_empty=True, max_intents=2),
            ("intents", [{"from": ["f001"], "description": "legacy"}]),
        )

    def test_reason_intent_extra_metadata_is_ignored_by_contract(self) -> None:
        from cairn.dispatcher.contracts import validate_reason_payload

        payload = {
            "accepted": True,
            "data": {
                "intents": [
                    {
                        "from": ["f001"],
                        "description": "next",
                        "priority_score": 0.9,
                        "intent_kind": " exploit ",
                        "tags": [" rce ", ""],
                        "score_reason": " direct path ",
                        "branch_key": " access.input.parser ",
                        "branch_depth": 2,
                        "expected_value": 0.82,
                    },
                    {"from": ["f002"], "description": "default"},
                ]
            },
        }

        kind, data = validate_reason_payload(payload, open_intents_empty=True, max_intents=3)

        self.assertEqual(kind, "intents")
        self.assertEqual(
            data,
            [
                {
                    "from": ["f001"],
                    "description": "next",
                    "priority_score": 0.9,
                    "intent_kind": " exploit ",
                    "tags": [" rce ", ""],
                    "score_reason": " direct path ",
                    "branch_key": " access.input.parser ",
                    "branch_depth": 2,
                    "expected_value": 0.82,
                },
                {"from": ["f002"], "description": "default"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
