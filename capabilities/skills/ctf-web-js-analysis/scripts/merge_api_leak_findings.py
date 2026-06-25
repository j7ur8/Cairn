#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALUE_LEVELS = {"high", "medium", "low", "info"}
OUTPUT_FILENAMES = {"information_api.json", "information_leak.json"}
NON_FINDING_FILENAMES = {
    "js_urls.json",
    "js_inventory.json",
    "har.json",
    "manifest.json",
    "package.json",
    "package-lock.json",
    "yarn.lock.json",
}
FINDING_FILENAME_SUFFIXES = (
    "_findings.json",
    "-findings.json",
    ".findings.json",
    "_tool_output.json",
    "-tool-output.json",
    ".tool-output.json",
)
FINDING_TOP_LEVEL_KEYS = {"apis", "api_findings", "leaks", "leak_findings"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def default_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "unknown",
        "url": None,
        "local_path": None,
        "sha256": None,
        "line": None,
        "column": None,
        "tool": item.get("tool"),
    }


def ensure_source(value: Any, item: dict[str, Any]) -> dict[str, Any]:
    return value if isinstance(value, dict) else default_source(item)


def normalize_value(item: dict[str, Any]) -> Any:
    if "value" in item:
        value = item.get("value")
        if isinstance(value, str) and value in VALUE_LEVELS:
            return value
        return value
    if "confidence" in item:
        return "low"
    return "info"


def has_finding_top_level_keys(path: Path) -> bool:
    try:
        data = load_json(path)
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and any(key in data for key in FINDING_TOP_LEVEL_KEYS)


def is_default_scan_input(path: Path) -> bool:
    name = path.name
    if name in OUTPUT_FILENAMES or name in NON_FINDING_FILENAMES:
        return False
    if any(name.endswith(suffix) for suffix in FINDING_FILENAME_SUFFIXES):
        return True
    return has_finding_top_level_keys(path)


def default_inputs(artifact_dir: Path) -> list[Path]:
    return [path for path in artifact_dir.glob("*.json") if is_default_scan_input(path)]


def normalize_api(item: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "id": item.get("id") or f"api-{idx:03d}",
        "url": item.get("url") or item.get("path"),
        "method": item.get("method"),
        "parameters": ensure_list(item.get("parameters")),
        "headers": ensure_list(item.get("headers")),
        "auth_context": item.get("auth_context"),
        "source": ensure_source(item.get("source"), item),
        "evidence": ensure_list(item.get("evidence")),
        "value": normalize_value(item),
        "notes": ensure_list(item.get("notes")),
    }


def normalize_leak(item: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "id": item.get("id") or f"leak-{idx:03d}",
        "value": normalize_value(item),
        "type": item.get("type") or "other",
        "source": ensure_source(item.get("source"), item),
        "evidence": ensure_list(item.get("evidence")),
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
        inputs = default_inputs(artifact_dir)

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
