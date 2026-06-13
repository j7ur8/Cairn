from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class IterJsonlTests(unittest.TestCase):
    def test_parses_object_lines_and_skips_noise(self) -> None:
        from cairn.dispatcher.workers.adapters._jsonl import iter_jsonl

        text = '\n{"a": 1}\nnot json\n  \n[1, 2]\n{"b": 2}\n'
        result = iter_jsonl(text)
        # Blank lines, non-JSON, and non-object JSON (the list) are dropped.
        self.assertEqual(result, [{"a": 1}, {"b": 2}])

    def test_empty_input_yields_empty_list(self) -> None:
        from cairn.dispatcher.workers.adapters._jsonl import iter_jsonl

        self.assertEqual(iter_jsonl(""), [])


class ExtractTextPartsTests(unittest.TestCase):
    def test_bare_string_passthrough(self) -> None:
        from cairn.dispatcher.workers.adapters._jsonl import extract_text_parts

        self.assertEqual(extract_text_parts("hello"), "hello")

    def test_non_list_non_str_returns_empty(self) -> None:
        from cairn.dispatcher.workers.adapters._jsonl import extract_text_parts

        self.assertEqual(extract_text_parts({"text": "x"}), "")
        self.assertEqual(extract_text_parts(None), "")

    def test_joins_text_items_without_predicate(self) -> None:
        from cairn.dispatcher.workers.adapters._jsonl import extract_text_parts

        content = [{"text": "a"}, {"type": "tool", "text": "b"}, {"no_text": 1}]
        # Without a predicate, any item with a string text contributes (codex).
        self.assertEqual(extract_text_parts(content), "a\nb")

    def test_predicate_filters_items(self) -> None:
        from cairn.dispatcher.workers.adapters._jsonl import extract_text_parts

        content = [{"type": "text", "text": "keep"}, {"type": "thinking", "text": "drop"}]
        # claudecode-style: only type == "text" contributes.
        result = extract_text_parts(content, predicate=lambda item: item.get("type") == "text")
        self.assertEqual(result, "keep")


if __name__ == "__main__":
    unittest.main()
