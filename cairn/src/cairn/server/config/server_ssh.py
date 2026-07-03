from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any

from fastapi import HTTPException

from cairn.server.config.server_certificates import ServerCertificateStore
from cairn.server.schemas.servers import ServerCommandRequest, ServerCommandResult
from cairn.shared.config import ServerAuthMethod, ServerResourceConfig


class ServerSshRunner:
    def __init__(self, certificate_store: ServerCertificateStore | None = None):
        self.certificate_store = certificate_store or ServerCertificateStore()

    def run(self, server: ServerResourceConfig, request: ServerCommandRequest) -> ServerCommandResult:
        failures: list[str] = []
        last_exit_code: int | None = None
        last_stdout = ""
        last_stderr = ""
        for method in server.auth_order:
            cleanup = lambda: None
            try:
                argv, cleanup = self._ssh_argv(server, request.command, method)
                completed = subprocess.run(
                    argv,
                    text=True,
                    capture_output=True,
                    timeout=request.timeout_seconds,
                    check=False,
                )
                if completed.returncode == 0:
                    return ServerCommandResult(
                        ok=True,
                        server_id=server.id,
                        command=request.command,
                        exit_code=completed.returncode,
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                        message=f"ok via {method}",
                    )
                last_exit_code = completed.returncode
                last_stdout = completed.stdout
                last_stderr = completed.stderr
                failures.append(f"{method}: ssh command failed with exit code {completed.returncode}")
            except subprocess.TimeoutExpired as exc:
                last_stdout = exc.stdout or ""
                last_stderr = exc.stderr or ""
                failures.append(f"{method}: ssh command timed out after {request.timeout_seconds}s")
            except HTTPException as exc:
                failures.append(f"{method}: {exc.detail}")
            except FileNotFoundError as exc:
                failures.append(f"{method}: {exc}")
            finally:
                cleanup()
        return ServerCommandResult(
            ok=False,
            server_id=server.id,
            command=request.command,
            exit_code=last_exit_code,
            stdout=last_stdout,
            stderr=last_stderr,
            message="; ".join(failures) or "no auth methods available",
        )

    def _ssh_argv(self, server: ServerResourceConfig, command: str, method: ServerAuthMethod) -> tuple[list[str], Any]:
        cleanup_callbacks = []
        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-p",
            str(server.port),
        ]
        if method == "password":
            if not server.password:
                raise HTTPException(400, f"server {server.id} password auth requires password")
            if not shutil.which("sshpass"):
                raise HTTPException(400, "password auth testing requires sshpass on this host")
            fd, password_path = tempfile.mkstemp(prefix="cairn-ssh-password-", text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(server.password)
                if not server.password.endswith("\n"):
                    handle.write("\n")
            os.chmod(password_path, 0o600)

            def cleanup_password() -> None:
                try:
                    os.unlink(password_path)
                except OSError:
                    pass

            cleanup_callbacks.append(cleanup_password)
            argv[2] = "BatchMode=no"
            argv.extend(["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"])
            argv = ["sshpass", "-f", password_path, *argv]
        if method == "private_key":
            if not server.private_key:
                raise HTTPException(400, f"server {server.id} private_key auth requires private_key")
            fd, key_path = tempfile.mkstemp(prefix="cairn-ssh-key-", text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(server.private_key)
                if not server.private_key.endswith("\n"):
                    handle.write("\n")
            os.chmod(key_path, 0o600)

            def cleanup_key() -> None:
                try:
                    os.unlink(key_path)
                except OSError:
                    pass

            cleanup_callbacks.append(cleanup_key)
            argv.extend(["-i", key_path])
        if method == "certificate":
            argv.extend(["-i", str(self.certificate_store.resolve(server))])
        argv.extend([f"{server.username}@{server.host}", command])

        def cleanup() -> None:
            for callback in cleanup_callbacks:
                callback()

        return argv, cleanup
