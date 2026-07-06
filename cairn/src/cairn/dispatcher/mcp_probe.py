from __future__ import annotations

import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairn.dispatcher.capability_constants import CAPABILITY_ROOT
from cairn.dispatcher.capability_mcp import mcp_json
from cairn.dispatcher.runtime.browser_provider import BrowserRuntimeContext, BrowserRuntimeLease, remove_temp_lease_file
from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.tasks.task_process import communicate_timeout
from cairn.shared.config import DispatchConfig, McpServerCapabilityConfig

MCP_PROBE_TIMEOUT_SECONDS = 8
MCP_PROBE_ROOT = f"{CAPABILITY_ROOT}/probe"
MCP_PROBE_PATH = f"{MCP_PROBE_ROOT}/mcp.json"
MCP_PROBE_SCRIPT_PATH = f"{CAPABILITY_ROOT}/probe_mcp.py"
MCP_PROBE_SCRIPT = r'''#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REQUEST_TIMEOUT = float(os.environ.get("CAIRN_MCP_PROBE_REQUEST_TIMEOUT", "5"))


def request(method, params=None, request_id=1):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def initialize_payload():
    return request(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cairn-mcp-probe", "version": "0.1.0"},
        },
        1,
    )


def _compact(value, limit=600):
    text = str(value or "").strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _read_response_line(stream):
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError("mcp server closed stdout before JSON-RPC response")
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "id" in payload:
            return payload


def _check_jsonrpc_response(payload, label):
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned non-object response")
    if payload.get("error") is not None:
        raise RuntimeError(f"{label} returned error: {_compact(payload.get('error'))}")
    if payload.get("result") is None:
        raise RuntimeError(f"{label} response missing result")


def probe_stdio(detail):
    command = detail.get("command")
    if not isinstance(command, str) or not command.strip():
        raise RuntimeError("stdio MCP missing command")
    args = detail.get("args") if isinstance(detail.get("args"), list) else []
    env = os.environ.copy()
    configured_env = detail.get("env") if isinstance(detail.get("env"), dict) else {}
    env.update({str(k): str(v) for k, v in configured_env.items()})
    proc = subprocess.Popen(
        [command, *[str(arg) for arg in args]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=False,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        init_payload = initialize_payload()
        proc.stdin.write((json.dumps(init_payload, separators=(",", ":")) + "\n").encode("utf-8"))
        proc.stdin.flush()
        init_response = _read_response_line(proc.stdout)
        _check_jsonrpc_response(init_response, init_payload["method"])
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        proc.stdin.write((json.dumps(initialized, separators=(",", ":")) + "\n").encode("utf-8"))
        proc.stdin.flush()
        for payload in (request("tools/list", {}, 2),):
            proc.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
            proc.stdin.flush()
            response = _read_response_line(proc.stdout)
            _check_jsonrpc_response(response, payload["method"])
        return "initialize + tools/list ok"
    finally:
        proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate(timeout=1)
        if proc.returncode not in (0, None, -15, -9):
            err = _compact(stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr)
            if err:
                raise RuntimeError(f"stdio process exited code={proc.returncode}: {err}")


def _post_json(url, headers, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    for key, value in headers.items():
        req.add_header(str(key), str(value))
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise RuntimeError(f"HTTP {status}")
            text = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                payload = _parse_sse_json(text)
            else:
                payload = json.loads(text)
            return payload, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {_compact(detail or exc.reason)}") from exc


def _parse_sse_json(text):
    data_lines = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if not data_lines:
        raise RuntimeError("SSE response missing data event")
    return json.loads("\n".join(data_lines))


def probe_http(detail):
    url = detail.get("url")
    if not isinstance(url, str) or not url.strip():
        raise RuntimeError("http MCP missing url")
    headers = detail.get("headers") if isinstance(detail.get("headers"), dict) else {}
    init_response, init_headers = _post_json(url, headers, initialize_payload())
    _check_jsonrpc_response(init_response, "initialize")
    session_id = init_headers.get("mcp-session-id") or init_headers.get("Mcp-Session-Id")
    tools_headers = dict(headers)
    if session_id:
        tools_headers["mcp-session-id"] = session_id
    tools_response, _ = _post_json(url, tools_headers, request("tools/list", {}, 2))
    _check_jsonrpc_response(tools_response, "tools/list")
    return "initialize + tools/list ok"


def main():
    if len(sys.argv) != 3:
        print("usage: probe_mcp.py <mcp.json> <server-id>", file=sys.stderr)
        return 2
    config_path, server_id = sys.argv[1:3]
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    detail = servers.get(server_id) if isinstance(servers, dict) else None
    if not isinstance(detail, dict):
        print(f"missing MCP server config: {server_id}", file=sys.stderr)
        return 2
    try:
        if detail.get("type") == "http":
            message = probe_http(detail)
        else:
            message = probe_stdio(detail)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


@dataclass(slots=True)
class McpProbeResult:
    capability_id: str
    status: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "status": self.status,
            "message": self.message,
        }


def run_mcp_probe_request(
    *,
    config: DispatchConfig,
    container_manager: ContainerManager,
    server_ids: list[str],
    cloak_sidecar_manager: CloakSidecarManager | None = None,
) -> dict[str, Any]:
    requested_ids = _dedupe_ids(server_ids) or [item.id for item in config.capabilities.mcp_servers]
    by_id = {item.id: item for item in config.capabilities.mcp_servers}
    missing = [
        McpProbeResult(capability_id=server_id, status="error", message=f"mcp_server not found: {server_id}")
        for server_id in requested_ids
        if server_id not in by_id
    ]
    targets = [by_id[server_id] for server_id in requested_ids if server_id in by_id]
    if not targets:
        return {"results": [item.to_dict() for item in missing]}

    container_name = container_manager.create_startup_container()
    provider_context = BrowserRuntimeContext(
        project_id="probe",
        task_instance_id=f"mcp-probe-{uuid.uuid4().hex}",
        network_mode=config.container.network_mode,
        cloak_sidecar_manager=cloak_sidecar_manager,
        container_name=container_name,
        lease_writer=container_manager,
        lease_root=f"{MCP_PROBE_ROOT}/leases",
    )
    runtime_leases: dict[str, BrowserRuntimeLease] = {}
    provider_errors: list[McpProbeResult] = []
    probe_targets: list[McpServerCapabilityConfig] = []
    try:
        for target in targets:
            try:
                lease = provider_context.acquire(target)
            except Exception as exc:  # noqa: BLE001
                provider_errors.append(McpProbeResult(target.id, "error", f"runtime provider failed: {exc}"))
                continue
            if lease is not None:
                runtime_leases[target.id] = lease
            probe_targets.append(target)
        for target in probe_targets:
            if target.source_path:
                container_manager.write_directory(
                    container_name,
                    f"{MCP_PROBE_ROOT}/mcp/{target.id}",
                    Path(target.source_path),
                )
        container_manager.write_text_file(
            container_name,
            MCP_PROBE_PATH,
            mcp_json(probe_targets, MCP_PROBE_ROOT, runtime_leases=runtime_leases),
        )
        container_manager.write_text_file(container_name, MCP_PROBE_SCRIPT_PATH, MCP_PROBE_SCRIPT)
        results = [_probe_one(container_manager, container_name, item) for item in probe_targets]
    finally:
        for lease in runtime_leases.values():
            lease.release()
            remove_temp_lease_file(lease)
        container_manager.remove_container(container_name, force=True)
    return {"results": [item.to_dict() for item in [*missing, *provider_errors, *results]]}


def _probe_one(
    container_manager: ContainerManager,
    container_name: str,
    mcp: McpServerCapabilityConfig,
) -> McpProbeResult:
    timeout = _timeout_seconds(mcp)
    process = container_manager.build_exec_process(
        container_name,
        {},
        ["python3", MCP_PROBE_SCRIPT_PATH, MCP_PROBE_PATH, mcp.id],
        timeout_seconds=timeout,
    )
    try:
        process.start()
        result = process.communicate(timeout=communicate_timeout(timeout))
    except Exception as exc:  # noqa: BLE001 - probe should report per-target failure.
        return McpProbeResult(mcp.id, "error", f"probe crashed: {exc}")
    if result.returncode == 0:
        return McpProbeResult(mcp.id, "ok", _preview(result.stdout) or "initialize + tools/list ok")
    message = _preview(result.stderr) or _preview(result.stdout) or f"probe failed code={result.returncode}"
    if result.timed_out:
        message = f"probe timed out after {timeout}s: {message}"
    command = _describe_mcp_command(mcp)
    return McpProbeResult(mcp.id, "error", f"{message} ({command})")


def _dedupe_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _timeout_seconds(mcp: McpServerCapabilityConfig) -> int:
    configured = max(1.0, min(float(mcp.healthcheck_timeout or 1.0), 30.0))
    return max(MCP_PROBE_TIMEOUT_SECONDS, int(configured) + 2)


def _preview(value: str, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _describe_mcp_command(mcp: McpServerCapabilityConfig) -> str:
    if mcp.transport == "http":
        return f"url={mcp.url or '-'}"
    parts = [mcp.command or "-", *list(mcp.args or [])]
    return "command=" + " ".join(shlex.quote(str(part)) for part in parts)
