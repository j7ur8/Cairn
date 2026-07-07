from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docker.models.containers import Container

try:
    from docker.errors import APIError, DockerException
except ModuleNotFoundError:  # Allows scheduler pure logic to import without Docker SDK.
    class DockerException(Exception):  # type: ignore[no-redef]
        pass

    class APIError(DockerException):  # type: ignore[no-redef]
        pass

LOG = logging.getLogger(__name__)
EXEC_KILL_JOIN_TIMEOUT_SECONDS = 5.0
DEFAULT_STREAM_TAIL_BYTES = 4 * 1024 * 1024
_PROC_PARENT_LIST_SCRIPT = r"""
for stat in /proc/[0-9]*/stat; do
    [ -r "$stat" ] || continue
    proc_pid=${stat#/proc/}
    proc_pid=${proc_pid%/stat}
    case "$proc_pid" in
        ""|*[!0-9]*) continue ;;
    esac
    if IFS= read -r line < "$stat"; then
        rest=${line##*) }
        set -- $rest
        proc_ppid=$2
        case "$proc_ppid" in
            ""|*[!0-9]*) continue ;;
        esac
        printf '%s %s\n' "$proc_pid" "$proc_ppid"
    fi
done
"""


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    cancel_reason: str | None = None
    truncated: bool = False


class _TextTailBuffer:
    def __init__(self, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        self._text = ""
        self._bytes = 0
        self.truncated = False

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        self._text += chunk
        self._bytes += len(chunk.encode("utf-8", errors="replace"))
        if self._bytes <= self.limit_bytes:
            return
        encoded = self._text.encode("utf-8", errors="replace")[-self.limit_bytes:]
        self._text = encoded.decode("utf-8", errors="ignore")
        self._bytes = len(self._text.encode("utf-8", errors="replace"))
        self.truncated = True

    def text(self) -> str:
        return self._text


class ManagedProcess:
    def __init__(
        self,
        container: Container,
        command: list[str],
        env: dict[str, str],
        user: str | None = None,
        workdir: str | None = None,
        tty: bool = False,
        on_output: Callable[[str, str], None] | None = None,
    ):
        self.command = command
        self.env = env
        self.user = user
        self.workdir = workdir
        self.tty = tty
        self.on_output = on_output
        self._container = container
        self._api = container.client.api
        self._exec_id: str | None = None
        self._reader: threading.Thread | None = None
        self._stdout = _TextTailBuffer(DEFAULT_STREAM_TAIL_BYTES)
        self._stderr = _TextTailBuffer(DEFAULT_STREAM_TAIL_BYTES)
        self._returncode: int | None = None
        self._timed_out = False
        self._cancel_reason: str | None = None
        self._read_error: str | None = None
        self._done = threading.Event()

    def start(self) -> None:
        exec_info = self._api.exec_create(
            self._container.id,
            self.command,
            stdout=True,
            stderr=True,
            stdin=False,
            tty=self.tty,
            environment=self.env,
            user=self.user,
            workdir=self.workdir,
        )
        self._exec_id = exec_info["Id"]
        self._reader = threading.Thread(target=self._read_stream, daemon=True)
        self._reader.start()

    def communicate(self, timeout: float | None) -> ProcessResult:
        assert self._reader is not None
        self._reader.join(timeout=timeout)
        if self._reader.is_alive():
            self._timed_out = True
            self.kill()
            self._reader.join(timeout=EXEC_KILL_JOIN_TIMEOUT_SECONDS)
        if self._reader.is_alive():
            if self._returncode is None:
                self._returncode = 137
            self._done.set()
        self._done.wait(timeout=0)
        if self._read_error and not self._stderr.text():
            self._stderr.append(self._read_error)
        return ProcessResult(
            returncode=self._returncode if self._returncode is not None else 1,
            stdout=self._stdout.text(),
            stderr=self._stderr.text(),
            timed_out=self._timed_out,
            cancelled=self._cancel_reason is not None,
            cancel_reason=self._cancel_reason,
            truncated=self._stdout.truncated or self._stderr.truncated,
        )

    def kill(self) -> None:
        if self._exec_id is None:
            return
        try:
            details = self._api.exec_inspect(self._exec_id)
        except DockerException as exc:
            LOG.warning("failed to inspect exec before kill exec_id=%s error=%s", self._exec_id, exc)
            return
        if not details.get("Running"):
            return
        pid = details.get("Pid")
        if not pid:
            LOG.warning("container exec missing pid for kill exec_id=%s", self._exec_id)
            return
        self._kill_pid(int(pid))

    def cancel(self, reason: str) -> None:
        if self._cancel_reason is None:
            self._cancel_reason = reason
        self.kill()

    def _read_stream(self) -> None:
        assert self._exec_id is not None
        stream: Any | None = None
        try:
            stream = self._api.exec_start(
                self._exec_id,
                detach=False,
                tty=self.tty,
                stream=True,
                demux=not self.tty,
            )
            for chunk in stream:
                stdout, stderr = self._split_chunk(chunk)
                if stdout:
                    self._stdout.append(stdout)
                    self._notify_output("stdout", stdout)
                if stderr:
                    self._stderr.append(stderr)
                    self._notify_output("stderr", stderr)
        except DockerException as exc:
            self._read_error = str(exc)
        finally:
            self._close_stream(stream)
            self._returncode = self._resolve_exit_code()
            self._done.set()

    @staticmethod
    def _close_stream(stream: Any | None) -> None:
        if stream is None:
            return
        close = getattr(stream, "close", None)
        if callable(close):
            with suppress(Exception):
                close()
        response = getattr(stream, "_response", None)
        response_close = getattr(response, "close", None)
        if callable(response_close):
            with suppress(Exception):
                response_close()

    def _resolve_exit_code(self) -> int:
        assert self._exec_id is not None
        deadline = time.monotonic() + EXEC_KILL_JOIN_TIMEOUT_SECONDS
        while True:
            try:
                details = self._api.exec_inspect(self._exec_id)
            except DockerException as exc:
                if self._read_error is None:
                    self._read_error = str(exc)
                return 137 if self._timed_out else 1
            exit_code = details.get("ExitCode")
            if exit_code is not None:
                return int(exit_code)
            if time.monotonic() >= deadline:
                return 137 if self._timed_out else 1
            time.sleep(0.1)

    def _kill_pid(self, pid: int) -> None:
        for descendant_pid in self._descendant_pids(pid):
            self._kill_single_pid(descendant_pid, log_failure=False)
        self._kill_single_pid(pid, log_failure=True)

    def _descendant_pids(self, pid: int) -> list[int]:
        pairs = self._proc_parent_pairs()
        if not pairs:
            return []
        children_by_parent: dict[int, list[int]] = {}
        for child_pid, parent_pid in pairs:
            if child_pid == parent_pid:
                continue
            children_by_parent.setdefault(parent_pid, []).append(child_pid)

        descendants: list[int] = []
        visited: set[int] = set()

        def visit(parent_pid: int) -> None:
            for child_pid in sorted(children_by_parent.get(parent_pid, [])):
                if child_pid in visited:
                    continue
                visited.add(child_pid)
                visit(child_pid)
                descendants.append(child_pid)

        visit(pid)
        return descendants

    def _proc_parent_pairs(self) -> list[tuple[int, int]]:
        for shell in ("/bin/sh", "sh"):
            try:
                result = self._container.exec_run(
                    [shell, "-c", _PROC_PARENT_LIST_SCRIPT],
                    stdout=True,
                    stderr=False,
                )
            except APIError as exc:
                LOG.debug("failed to inspect container process tree shell=%s container=%s error=%s", shell, self._container.name, exc)
                continue
            exit_code = self._exec_result_exit_code(result)
            if exit_code not in (None, 0):
                continue
            return self._parse_proc_parent_pairs(self._exec_result_output(result))
        return []

    @staticmethod
    def _parse_proc_parent_pairs(output: bytes | str | None) -> list[tuple[int, int]]:
        pairs: list[tuple[int, int]] = []
        for line in ManagedProcess._decode(output).splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            try:
                child_pid = int(parts[0])
                parent_pid = int(parts[1])
            except ValueError:
                continue
            pairs.append((child_pid, parent_pid))
        return pairs

    def _kill_single_pid(self, pid: int, *, log_failure: bool) -> None:
        last_error: str | None = None
        for command in (
            ["kill", "-KILL", str(pid)],
            ["/bin/sh", "-lc", f"kill -KILL {pid}"],
            ["sh", "-lc", f"kill -KILL {pid}"],
        ):
            try:
                result = self._container.exec_run(command, stdout=False, stderr=False)
            except APIError as exc:
                last_error = str(exc)
                continue
            exit_code = self._exec_result_exit_code(result)
            if exit_code in (None, 0, 1):
                return
        if log_failure and last_error is not None:
            LOG.warning("failed to kill container exec pid=%s container=%s error=%s", pid, self._container.name, last_error)

    @staticmethod
    def _exec_result_exit_code(result: Any) -> int | None:
        if hasattr(result, "exit_code"):
            exit_code = result.exit_code
            return int(exit_code) if exit_code is not None else None
        if isinstance(result, tuple) and result:
            exit_code = result[0]
            return int(exit_code) if exit_code is not None else None
        return None

    @staticmethod
    def _exec_result_output(result: Any) -> bytes | str | None:
        if hasattr(result, "output"):
            return result.output
        if isinstance(result, tuple) and len(result) > 1:
            return result[1]
        return None

    def _notify_output(self, stream: str, chunk: str) -> None:
        if self.on_output is None:
            return
        try:
            self.on_output(stream, chunk)
        except Exception as exc:
            LOG.debug("process output callback failed stream=%s error=%s", stream, exc)

    @staticmethod
    def _split_chunk(chunk: Any) -> tuple[str, str]:
        if isinstance(chunk, tuple):
            stdout, stderr = chunk
        else:
            stdout, stderr = chunk, None
        return ManagedProcess._decode(stdout), ManagedProcess._decode(stderr)

    @staticmethod
    def _decode(chunk: bytes | str | None) -> str:
        if chunk is None:
            return ""
        if isinstance(chunk, bytes):
            return chunk.decode("utf-8", errors="replace")
        return chunk
