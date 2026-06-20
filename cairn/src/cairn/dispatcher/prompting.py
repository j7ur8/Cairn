from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Any

from cairn.shared.config import RemoteSupportConfig

LOG = logging.getLogger(__name__)
DEFAULT_PROMPT_GROUP = "default"


def load_prompt(name: str) -> str:
    return resources.files("cairn.dispatcher.prompts").joinpath(DEFAULT_PROMPT_GROUP).joinpath(name).read_text(encoding="utf-8")


def load_prompt_from_execution_config(
    execution_config: dict | None,
    name: str,
    reporter: Any | None = None,
) -> str:
    prompt_snapshot = execution_config.get("prompt_snapshot") if isinstance(execution_config, dict) else None
    prompts = prompt_snapshot.get("prompts") if isinstance(prompt_snapshot, dict) else None
    if isinstance(prompts, dict):
        content = prompts.get(name)
        if isinstance(content, str):
            return content
    message = f"execution config prompt snapshot missing {name}; using default prompt template"
    LOG.warning(message)
    if reporter is not None:
        reporter.emit_error("prompt_snapshot", "warning", message)
    return load_prompt(name)


def render_prompt(template: str, replacements: dict[str, str]) -> str:
    text = template
    for key, value in replacements.items():
        text = text.replace("{" + key + "}", value)
    return text


def format_fact_ids(fact_ids: list[str]) -> str:
    return format_json_block(fact_ids)


def format_open_intents(intents: list[dict[str, Any]]) -> str:
    return format_json_block(intents)


def format_hints(hints: list[dict[str, Any]]) -> str:
    return format_json_block(hints)


def format_json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def format_remote_support_appendix(remote_support: RemoteSupportConfig) -> str:
    if not remote_support.has_available_resource:
        return ""

    lines = [
        "Authorized Remote Support may be available through environment variables:",
        "",
    ]
    if remote_support.dnslog_configured:
        lines.extend(
            [
                "- CAIRN_DNSLOG_URL:",
                "  Use for DNSLog/OOB checks such as SSRF, XXE, RCE callbacks, JNDI verification, or blind vulnerability confirmation.",
                "",
            ]
        )
    if remote_support.ssh_configured:
        lines.extend(
            [
                "- CAIRN_REMOTE_SSH_HOST",
                "- CAIRN_REMOTE_SSH_PORT",
                "- CAIRN_REMOTE_SSH_USERNAME",
                "- CAIRN_REMOTE_SSH_PASSWORD:",
                "  SSH credentials for an authorized remote helper server. You may use it to host payloads, start HTTP/JNDI/listener services, receive reverse shells, run callbacks, or stage challenge-specific tooling.",
                "",
            ]
        )
    lines.extend(
        [
            "Use these resources only for the current Cairn project/challenge.",
            "Do not treat their existence as a solved fact.",
            "Only report findings that are verified against the challenge target.",
        ]
    )
    return "\n".join(lines)
