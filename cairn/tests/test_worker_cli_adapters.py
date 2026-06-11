"""Regression tests for worker CLI adapter command construction and trace parsing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class ClaudeCodeDriverCommandTests(unittest.TestCase):
    def _worker(self):
        from cairn.shared.dispatch_config import WorkerConfig
        return WorkerConfig(
            name="claude",
            type="claudecode",
            task_types=["bootstrap"],
            max_running=1,
            priority=0,
            env={
                "ANTHROPIC_MODEL": "claude-sonnet-4-6",
                "ANTHROPIC_BASE_URL": "https://api.example.test",
                "ANTHROPIC_AUTH_TOKEN": "secret",
            },
        )

    def _worker_with_effort(self):
        worker = self._worker()
        worker.env["CAIRN_MODEL_REASONING_EFFORT"] = "xhigh"
        return worker

    def test_build_execute_uses_print_mode(self) -> None:
        from cairn.dispatcher.workers.adapters.claudecode import ClaudeCodeDriver

        result = ClaudeCodeDriver().build_execute(self._worker(), "hello", "11111111-1111-1111-1111-111111111111")
        self.assertIn("--print", result.argv)
        self.assertNotIn("-p", result.argv)
        self.assertFalse(ClaudeCodeDriver().requires_tty())

    def test_build_conclude_uses_print_mode(self) -> None:
        from cairn.dispatcher.workers.adapters.claudecode import ClaudeCodeDriver

        argv = ClaudeCodeDriver().build_conclude(
            self._worker(),
            "hello",
            "11111111-1111-1111-1111-111111111111",
        )
        self.assertIn("--print", argv)
        self.assertNotIn("-p", argv)

    def test_build_execute_includes_effort_when_configured(self) -> None:
        from cairn.dispatcher.workers.adapters.claudecode import ClaudeCodeDriver

        result = ClaudeCodeDriver().build_execute(
            self._worker_with_effort(),
            "hello",
            "11111111-1111-1111-1111-111111111111",
        )

        self.assertIn("--effort", result.argv)
        self.assertEqual(result.argv[result.argv.index("--effort") + 1], "xhigh")

    def test_build_execute_includes_claude_session_plugin_and_skill_dir(self) -> None:
        from cairn.dispatcher.workers.adapters.claudecode import ClaudeCodeDriver
        from cairn.dispatcher.workers.base import WorkerExecutionContext

        context = WorkerExecutionContext(
            mcp_config_path="/tmp/cairn-capabilities/proj/task/mcp.json",
            skill_root="/tmp/cairn-capabilities/proj/task/skills",
            claude_plugin_dir="/tmp/cairn-capabilities/proj/task/claude-plugin",
        )
        result = ClaudeCodeDriver().build_execute(
            self._worker(),
            "hello",
            "11111111-1111-1111-1111-111111111111",
            context,
        )

        self.assertIn("--plugin-dir", result.argv)
        self.assertEqual(
            result.argv[result.argv.index("--plugin-dir") + 1],
            "/tmp/cairn-capabilities/proj/task/claude-plugin",
        )
        self.assertIn("--add-dir", result.argv)
        self.assertEqual(
            result.argv[result.argv.index("--add-dir") + 1],
            "/tmp/cairn-capabilities/proj/task/skills",
        )

    def test_build_conclude_includes_claude_session_plugin(self) -> None:
        from cairn.dispatcher.workers.adapters.claudecode import ClaudeCodeDriver
        from cairn.dispatcher.workers.base import WorkerExecutionContext

        context = WorkerExecutionContext(
            skill_root="/tmp/cairn-capabilities/proj/task/skills",
            claude_plugin_dir="/tmp/cairn-capabilities/proj/task/claude-plugin",
        )
        argv = ClaudeCodeDriver().build_conclude(
            self._worker(),
            "hello",
            "11111111-1111-1111-1111-111111111111",
            context,
        )

        self.assertIn("--plugin-dir", argv)
        self.assertEqual(
            argv[argv.index("--plugin-dir") + 1],
            "/tmp/cairn-capabilities/proj/task/claude-plugin",
        )


class CodexDriverCommandTests(unittest.TestCase):
    def _worker(self):
        from cairn.shared.dispatch_config import WorkerConfig
        return WorkerConfig(
            name="codex",
            type="codex",
            task_types=["bootstrap"],
            max_running=1,
            priority=0,
            env={
                "CODEX_MODEL": "gpt-test",
                "CODEX_BASE_URL": "https://api.example.test/v1",
                "OPENAI_API_KEY": "secret",
            },
        )

    def _worker_with_effort(self):
        worker = self._worker()
        worker.env["CAIRN_MODEL_REASONING_EFFORT"] = "xhigh"
        return worker

    def test_build_execute_uses_noninteractive_guardrails(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver

        result = CodexDriver().build_execute(self._worker(), "hello", None)
        self.assertEqual(result.argv[:4], ["env", "CODEX_NON_INTERACTIVE=1", "codex", "exec"])
        self.assertTrue(CodexDriver().requires_tty())
        self.assertNotIn("--ephemeral", result.argv)
        self.assertIn("--ignore-user-config", result.argv)
        self.assertIn("--ignore-rules", result.argv)
        self.assertIn("--skip-git-repo-check", result.argv)

    def test_build_healthcheck_uses_same_guardrails(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver

        argv = CodexDriver().build_healthcheck(self._worker())
        self.assertEqual(argv[:4], ["env", "CODEX_NON_INTERACTIVE=1", "codex", "exec"])
        self.assertIn("--ephemeral", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)

    def test_build_conclude_uses_noninteractive_ephemeral_invocation(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver

        argv = CodexDriver().build_conclude(
            self._worker(),
            "hello",
            "11111111-1111-1111-1111-111111111111",
        )
        self.assertEqual(argv[:5], ["env", "CODEX_NON_INTERACTIVE=1", "codex", "exec", "resume"])
        self.assertNotIn("--ephemeral", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertIn("--skip-git-repo-check", argv)

    def test_build_execute_uses_configured_reasoning_effort(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver

        result = CodexDriver().build_execute(self._worker_with_effort(), "hello", None)
        joined = " ".join(result.argv)
        self.assertIn('model_reasoning_effort="xhigh"', joined)

    def test_build_conclude_omits_resume_unsupported_add_dir(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver
        from cairn.dispatcher.workers.base import WorkerExecutionContext

        context = WorkerExecutionContext(
            skill_root="/tmp/cairn-capabilities/proj/skills",
            mcp_servers=[{
                "id": "kali",
                "transport": "http",
                "url": "https://example.test/mcp",
                "headers": {"Authorization": "Bearer tk-1"},
            }],
        )
        argv = CodexDriver().build_conclude(
            self._worker(),
            "hello",
            "11111111-1111-1111-1111-111111111111",
            context,
        )
        joined = " ".join(argv)
        self.assertNotIn("--add-dir", argv)
        self.assertNotIn("/tmp/cairn-capabilities/proj/skills", argv)
        self.assertIn('mcp_servers.kali.url="https://example.test/mcp"', joined)
        self.assertIn('mcp_servers.kali.headers.Authorization="Bearer tk-1"', joined)

    def test_build_execute_keeps_add_dir_for_skill_access(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver
        from cairn.dispatcher.workers.base import WorkerExecutionContext

        context = WorkerExecutionContext(
            skill_root="/tmp/cairn-capabilities/proj/skills",
            claude_plugin_dir="/tmp/cairn-capabilities/proj/claude-plugin",
        )
        result = CodexDriver().build_execute(self._worker(), "hello", None, context)
        self.assertIn("--add-dir", result.argv)
        self.assertIn("/tmp/cairn-capabilities/proj/skills", result.argv)
        self.assertNotIn("--plugin-dir", result.argv)
        self.assertNotIn("/tmp/cairn-capabilities/proj/claude-plugin", result.argv)


class CodexTraceParserTests(unittest.TestCase):
    def test_stdin_notice_is_system_event(self) -> None:
        from cairn.dispatcher.observability.trace import make_trace_parser

        parser = make_trace_parser("codex_jsonl", "bootstrap")
        assert parser is not None
        events = parser.feed("Reading additional input from stdin...\n")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "system_event")
        self.assertEqual(events[0].metadata.get("notice_type"), "stdin_scan")

    def test_stdin_notice_does_not_block_following_jsonl(self) -> None:
        from cairn.dispatcher.observability.trace import make_trace_parser

        parser = make_trace_parser("codex_jsonl", "bootstrap")
        assert parser is not None
        events = parser.feed(
            "Reading additional input from stdin...\n"
            '{"type":"event_msg","payload":{"type":"agent_message","message":"pong"}}\n'
        )
        self.assertEqual([event.kind for event in events], ["system_event", "agent_message"])
        self.assertEqual(events[-1].content, "pong")

    def test_current_codex_jsonl_emits_command_events(self) -> None:
        from cairn.dispatcher.observability.trace import make_trace_parser

        parser = make_trace_parser("codex_jsonl", "bootstrap")
        assert parser is not None
        events = parser.feed(
            '{"type":"thread.started","thread_id":"019e9289-9f78-7b12-a33f-89252dcd62ac"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"starting"}}\n'
            '{"type":"item.started","item":{"id":"item_1","type":"command_execution","command":"/bin/bash -lc \\"pwd\\"","aggregated_output":"","exit_code":null,"status":"in_progress"}}\n'
            '{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"/bin/bash -lc \\"pwd\\"","aggregated_output":"/home/kali/workspace\\n","exit_code":0,"status":"completed"}}\n'
        )
        self.assertEqual(
            [event.kind for event in events],
            ["session_init", "system_event", "agent_message", "command_start", "command_end"],
        )
        self.assertEqual(parser.session_id, "019e9289-9f78-7b12-a33f-89252dcd62ac")
        self.assertEqual(events[-1].metadata.get("output"), "/home/kali/workspace\n")

    def test_codex_cli_diagnostic_line_is_error_not_trace_parse(self) -> None:
        from cairn.dispatcher.observability.trace import make_trace_parser

        parser = make_trace_parser("codex_jsonl", "explore_conclude")
        assert parser is not None
        events = parser.feed("\x1b[1m\x1b[31merror:\x1b[0m unexpected argument '\x1b[33m--add-dir\x1b[0m' found\n")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "error")
        self.assertEqual(events[0].stream, "error")
        self.assertEqual(events[0].metadata.get("notice_type"), "codex_cli_diagnostic")
        self.assertIn("unexpected argument", events[0].content)

    def test_current_codex_jsonl_extracts_session_and_response_text(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver

        stdout = (
            '{"type":"thread.started","thread_id":"019e9289-9f78-7b12-a33f-89252dcd62ac"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"{\\"accepted\\":true}"}}\n'
        )
        driver = CodexDriver()
        self.assertEqual(
            driver.extract_session(None, stdout, ""),
            "019e9289-9f78-7b12-a33f-89252dcd62ac",
        )
        self.assertEqual(driver.extract_response_text(stdout, ""), '{"accepted":true}')

    def test_current_codex_jsonl_extracts_last_agent_message_not_event_wrapper(self) -> None:
        from cairn.dispatcher.workers.adapters.codex import CodexDriver

        stdout = (
            '{"type":"thread.started","thread_id":"019e9289-9f78-7b12-a33f-89252dcd62ac"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message",'
            '"text":"{\\"accepted\\":true,\\"data\\":{\\"fact\\":{\\"description\\":\\"ok\\"}}}"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        )

        self.assertEqual(
            CodexDriver().extract_response_text(stdout, ""),
            '{"accepted":true,"data":{"fact":{"description":"ok"}}}',
        )


class ClaudeTraceParserTests(unittest.TestCase):
    def test_thinking_tokens_system_event_is_usage(self) -> None:
        from cairn.dispatcher.observability.trace import make_trace_parser

        parser = make_trace_parser("claude_stream_json", "explore_execute")
        assert parser is not None
        events = parser.feed(
            '{"type":"system","subtype":"thinking_tokens","thinking_tokens":123,"session_id":"s1"}\n'
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "usage")
        self.assertEqual(events[0].stream, "system")
        self.assertEqual(events[0].content, "token usage")
        self.assertEqual(events[0].metadata.get("thinking_tokens"), 123)
        self.assertEqual(events[0].metadata.get("session_id"), "s1")

    def test_api_retry_system_event_still_api_retry(self) -> None:
        from cairn.dispatcher.observability.trace import make_trace_parser

        parser = make_trace_parser("claude_stream_json", "explore_execute")
        assert parser is not None
        events = parser.feed(
            '{"type":"system","subtype":"api_retry","attempt":1,"max_retries":3,"session_id":"s1"}\n'
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "api_retry")
        self.assertEqual(events[0].content, "api retry 1/3")

    def test_unknown_system_event_still_system_event(self) -> None:
        from cairn.dispatcher.observability.trace import make_trace_parser

        parser = make_trace_parser("claude_stream_json", "explore_execute")
        assert parser is not None
        events = parser.feed('{"type":"system","subtype":"custom_notice","session_id":"s1"}\n')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "system_event")
        self.assertEqual(events[0].content, "system: custom_notice")


if __name__ == "__main__":
    unittest.main()
