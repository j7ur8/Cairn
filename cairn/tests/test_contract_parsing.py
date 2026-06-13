from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class ContractParsingTests(unittest.TestCase):
    def test_conclude_parses_sentinel_fact_text(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        stdout = (
            '{"type":"thread.started","thread_id":"t1"}\n'
            '32173462130721312360912sentinel fact32173462130721312360912\n'
            '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
        )

        self.assertEqual(parse_sentinel_fact_output(stdout), "sentinel fact")

    def test_conclude_parses_multiline_sentinel_fact_text(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        stdout = (
            "32173462130721312360912"
            "line one\n\n## Heading\n- item"
            "32173462130721312360912"
        )

        self.assertEqual(parse_sentinel_fact_output(stdout), "line one\n\n## Heading\n- item")

    def test_conclude_rejects_missing_sentinel(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "no sentinel fact found"):
            parse_sentinel_fact_output("plain error without markers")

    def test_conclude_rejects_empty_sentinel_fact(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            parse_sentinel_fact_output(
                "32173462130721312360912   \n  32173462130721312360912"
            )

    def test_conclude_rejects_multiple_sentinel_facts(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "multiple sentinel facts"):
            parse_sentinel_fact_output(
                "32173462130721312360912one32173462130721312360912"
                "32173462130721312360912two32173462130721312360912"
            )

    def test_conclude_rejects_json_inside_sentinel(self) -> None:
        from cairn.dispatcher.contracts import parse_sentinel_fact_output

        with self.assertRaisesRegex(ValueError, "plain text, not JSON"):
            parse_sentinel_fact_output(
                '32173462130721312360912{"accepted":true,"data":{"description":"old"}}32173462130721312360912'
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


if __name__ == "__main__":
    unittest.main()
