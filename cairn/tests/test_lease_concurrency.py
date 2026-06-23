from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class _RecordingProcess:
    """Captures cancel/kill calls for assertions; thread-safe counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.cancel_reasons: list[str] = []
        self.kill_count = 0

    def cancel(self, reason: str) -> None:
        with self._lock:
            self.cancel_reasons.append(reason)

    def kill(self) -> None:
        with self._lock:
            self.kill_count += 1


class TaskCancellationHandoffTests(unittest.TestCase):
    """Pins the lease handoff invariant: a cancel requested before the process
    attaches must still be delivered exactly once, regardless of ordering."""

    def test_cancel_before_attach_is_delivered_on_attach(self) -> None:
        from cairn.dispatcher.runtime.cancellation import TaskCancellation

        cancellation = TaskCancellation()
        proc = _RecordingProcess()

        first = cancellation.cancel("deleted")
        # No process attached yet, so nothing cancelled at the source.
        self.assertEqual(proc.cancel_reasons, [])
        self.assertTrue(first)
        self.assertTrue(cancellation.is_cancelled)

        # Attaching after the cancel must replay the reason to the process.
        cancellation.attach_process(proc)
        self.assertEqual(proc.cancel_reasons, ["deleted"])

    def test_cancel_after_attach_reaches_process(self) -> None:
        from cairn.dispatcher.runtime.cancellation import TaskCancellation

        cancellation = TaskCancellation()
        proc = _RecordingProcess()
        cancellation.attach_process(proc)

        self.assertTrue(cancellation.cancel("stopped"))
        self.assertEqual(proc.cancel_reasons, ["stopped"])

    def test_second_cancel_returns_false_and_keeps_first_reason(self) -> None:
        from cairn.dispatcher.runtime.cancellation import TaskCancellation

        cancellation = TaskCancellation()
        proc = _RecordingProcess()
        cancellation.attach_process(proc)

        self.assertTrue(cancellation.cancel("first"))
        self.assertFalse(cancellation.cancel("second"))
        # reason reflects the first winner.
        self.assertEqual(cancellation.reason, "first")
        self.assertEqual(proc.cancel_reasons, ["first"])

    def test_concurrent_cancels_have_single_winner(self) -> None:
        from cairn.dispatcher.runtime.cancellation import TaskCancellation

        cancellation = TaskCancellation()
        cancellation.attach_process(_RecordingProcess())

        results: list[bool] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(8)

        def worker(idx: int) -> None:
            barrier.wait()
            won = cancellation.cancel(f"reason-{idx}")
            with results_lock:
                results.append(won)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(1 for r in results if r), 1, "exactly one cancel should win")


class HeartbeatFailureVisibilityTests(unittest.TestCase):
    def test_failure_published_before_kill_observable(self) -> None:
        from cairn.dispatcher.runtime.heartbeat import HeartbeatLease

        # _heartbeat is never invoked here; we drive _fail() directly to assert
        # the failure becomes visible and the attached process is killed.
        lease = HeartbeatLease(heartbeat=lambda: None, scope="test", worker_name="mock", interval=1)
        proc = _RecordingProcess()
        lease.attach_process(proc)

        self.assertIsNone(lease.failure)
        lease._fail(409, "lease lost")

        failure = lease.failure
        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure.status_code, 409)
        self.assertEqual(proc.kill_count, 1)

    def test_fail_without_attached_process_is_safe(self) -> None:
        from cairn.dispatcher.runtime.heartbeat import HeartbeatLease

        lease = HeartbeatLease(heartbeat=lambda: None, scope="test", worker_name="mock", interval=1)
        lease._fail(403, "forbidden")
        failure = lease.failure
        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure.status_code, 403)


class ManagedProcessKillTests(unittest.TestCase):
    def _process(self, container) -> object:
        from cairn.dispatcher.runtime.process import ManagedProcess

        return ManagedProcess(container, ["run"], {})

    def test_kill_pid_kills_descendants_before_parent(self) -> None:
        container = mock.Mock()
        container.name = "worker"
        container.client.api = mock.Mock()
        commands: list[list[str]] = []
        proc_listing = "\n".join(
            [
                "10 1",
                "11 10",
                "12 10",
                "13 11",
                "14 13",
            ]
        )

        def exec_run(command, **_kwargs):
            commands.append(command)
            if command[:2] == ["/bin/sh", "-c"]:
                return SimpleNamespace(exit_code=0, output=proc_listing.encode())
            return SimpleNamespace(exit_code=0, output=b"")

        container.exec_run.side_effect = exec_run
        process = self._process(container)

        process._kill_pid(10)

        self.assertEqual(
            [command for command in commands if command and command[0] == "kill"],
            [
                ["kill", "-KILL", "14"],
                ["kill", "-KILL", "13"],
                ["kill", "-KILL", "11"],
                ["kill", "-KILL", "12"],
                ["kill", "-KILL", "10"],
            ],
        )

    def test_kill_pid_falls_back_to_direct_kill_when_proc_listing_fails(self) -> None:
        from cairn.dispatcher.runtime.process import APIError

        container = mock.Mock()
        container.name = "worker"
        container.client.api = mock.Mock()
        commands: list[list[str]] = []

        def exec_run(command, **_kwargs):
            commands.append(command)
            if command[:2] in (["/bin/sh", "-c"], ["sh", "-c"]):
                return SimpleNamespace(exit_code=2, output=b"")
            return SimpleNamespace(exit_code=0, output=b"")

        container.exec_run.side_effect = exec_run
        process = self._process(container)

        process._kill_pid(42)

        self.assertEqual(commands[-1], ["kill", "-KILL", "42"])
        self.assertEqual([command for command in commands if command and command[0] == "kill"], [["kill", "-KILL", "42"]])

        container.exec_run.side_effect = APIError("docker failed")
        process._kill_pid(42)

    def test_kill_pid_without_children_matches_direct_kill(self) -> None:
        container = mock.Mock()
        container.name = "worker"
        container.client.api = mock.Mock()
        commands: list[list[str]] = []

        def exec_run(command, **_kwargs):
            commands.append(command)
            if command[:2] == ["/bin/sh", "-c"]:
                return SimpleNamespace(exit_code=0, output=b"42 1\n")
            return SimpleNamespace(exit_code=0, output=b"")

        container.exec_run.side_effect = exec_run
        process = self._process(container)

        process._kill_pid(42)

        self.assertEqual([command for command in commands if command and command[0] == "kill"], [["kill", "-KILL", "42"]])


if __name__ == "__main__":
    unittest.main()
