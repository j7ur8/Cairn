#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalize_api(item: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "id": item.get("id") or f"api-{idx:03d}",
        "url": item.get("url") or item.get("path"),
        "method": item.get("method"),
        "parameters": ensure_list(item.get("parameters")),
        "headers": ensure_list(item.get("headers")),
        "auth_context": item.get("auth_context"),
        "source": item.get("source") or {"type": "unknown", "url": None, "local_path": None, "sha256": None, "tool": item.get("tool")},
        "evidence": ensure_list(item.get("evidence")),
        "confidence": item.get("confidence") or "static_candidate",
        "notes": ensure_list(item.get("notes")),
    }


def normalize_leak(item: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "id": item.get("id") or f"leak-{idx:03d}",
        "type": item.get("type") or "other",
        "summary": item.get("summary") or item.get("description") or "Potential frontend leak",
        "value_redacted": item.get("value_redacted") or item.get("redacted"),
        "value_sha256": item.get("value_sha256"),
        "severity": item.get("severity") or "unknown",
        "source": item.get("source") or {"type": "unknown", "url": None, "local_path": None, "sha256": None, "tool": item.get("tool")},
        "evidence": ensure_list(item.get("evidence")),
        "confidence": item.get("confidence") or "static_candidate",
        "notes": ensure_list(item.get("notes")),
    }


def collect(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = load_json(path)
    api_items: list[dict[str, Any]] = []
    leak_items: list[dict[str, Any]] = []
    if isinstance(data, dict):
        api_items.extend(item for item in ensure_list(data.get("apis")) if isinstance(item, dict))
        api_items.extend(item for item in ensure_list(data.get("api_findings")) if isinstance(item, dict))
        leak_items.extend(item for item in ensure_list(data.get("leaks")) if isinstance(item, dict))
        leak_items.extend(item for item in ensure_list(data.get("leak_findings")) if isinstance(item, dict))
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or item.get("category") or "").lower()
            if "api" in kind or item.get("url") or item.get("path"):
                api_items.append(item)
            else:
                leak_items.append(item)
    return api_items, leak_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge tool outputs into information_api.json and information_leak.json.")
    parser.add_argument("--artifact-dir", default=".", help="Directory to scan for existing information_*.json when no tool output is given.")
    parser.add_argument("--tool-output", action="append", default=[], help="Tool output JSON file. Can be passed multiple times.")
    parser.add_argument("--output-dir", required=True, help="Directory where fixed output JSON files are written.")
    parser.add_argument("--target", default=None)
    args = parser.parse_args()

    inputs = [Path(item) for item in args.tool_output]
    if not inputs:
        artifact_dir = Path(args.artifact_dir)
        inputs = [path for path in artifact_dir.glob("*.json") if path.name not in {"information_api.json", "information_leak.json"}]

    apis: list[dict[str, Any]] = []
    leaks: list[dict[str, Any]] = []
    for path in inputs:
        if not path.exists():
            continue
        try:
            api_items, leak_items = collect(path)
        except (json.JSONDecodeError, OSError):
            continue
        apis.extend(api_items)
        leaks.extend(leak_items)

    common = {
        "schema_version": "1.0",
        "target": args.target,
        "generated_at": now(),
        "tool": "ctf-web-js-analysis",
        "notes": [],
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "information_api.json").write_text(
        json.dumps({**common, "apis": [normalize_api(item, i + 1) for i, item in enumerate(apis)]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "information_leak.json").write_text(
        json.dumps({**common, "leaks": [normalize_leak(item, i + 1) for i, item in enumerate(leaks)]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
