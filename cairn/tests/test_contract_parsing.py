from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class ContractParsingTests(unittest.TestCase):
    def test_bootstrap_conclude_standard_wrapper_passes(self) -> None:
        from cairn.dispatcher.contracts import (
            parse_json_output,
            validate_bootstrap_conclude_payload,
        )

        payload = parse_json_output(
            '{"accepted":true,"data":{"fact":{"description":"confirmed fact"}}}'
        )

        self.assertEqual(
            validate_bootstrap_conclude_payload(payload),
            ("fact", "confirmed fact"),
        )

    def test_bootstrap_conclude_naked_fact_is_normalized(self) -> None:
        from cairn.dispatcher.contracts import (
            parse_json_output,
            validate_bootstrap_conclude_payload,
        )

        payload = parse_json_output('{"fact":{"description":"legacy fact"}}')

        self.assertEqual(payload["accepted"], True)
        self.assertEqual(
            validate_bootstrap_conclude_payload(payload),
            ("fact", "legacy fact"),
        )

    def test_codex_agent_message_protocol_json_is_preferred_over_event(self) -> None:
        from cairn.dispatcher.contracts import (
            parse_json_output,
            validate_bootstrap_conclude_payload,
        )

        stdout = (
            '{"type":"thread.started","thread_id":"t1"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message",'
            '"text":"{\\"accepted\\":true,\\"data\\":{\\"fact\\":{\\"description\\":\\"codex fact\\"}}}"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
        )

        payload = parse_json_output(stdout)

        self.assertEqual(payload["accepted"], True)
        self.assertEqual(
            validate_bootstrap_conclude_payload(payload),
            ("fact", "codex fact"),
        )

    def test_codex_event_without_protocol_payload_still_fails(self) -> None:
        from cairn.dispatcher.contracts import parse_json_output

        stdout = '{"type":"turn.started"}\n{"type":"turn.completed"}\n'

        with self.assertRaisesRegex(ValueError, "no JSON object found"):
            parse_json_output(stdout)


if __name__ == "__main__":
    unittest.main()
