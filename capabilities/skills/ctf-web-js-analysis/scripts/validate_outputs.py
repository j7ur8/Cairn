#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


VALUE_LEVELS = {"high", "medium", "low", "info"}
API_FIELDS = {
    "id",
    "url",
    "method",
    "parameters",
    "headers",
    "auth_context",
    "source",
    "evidence",
    "value",
    "notes",
}
LEAK_FIELDS = {"id", "value", "type", "source", "evidence"}


def load_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{path}: file not found")
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except OSError as exc:
        errors.append(f"{path}: cannot read file: {exc}")
    return None


def require_object(value: Any, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{label}: expected object")
        return None
    return value


def validate_common(data: dict[str, Any], finding_key: str, path: Path, errors: list[str]) -> list[Any]:
    for key in ("schema_version", "target", "generated_at", "tool", "notes", finding_key):
        if key not in data:
            errors.append(f"{path}: missing top-level field {key!r}")
    if "notes" in data and not isinstance(data["notes"], list):
        errors.append(f"{path}: top-level 'notes' must be an array")
    findings = data.get(finding_key)
    if not isinstance(findings, list):
        errors.append(f"{path}: top-level {finding_key!r} must be an array")
        return []
    return findings


def validate_value(value: Any, label: str, errors: list[str]) -> None:
    if value not in VALUE_LEVELS:
        errors.append(f"{label}: 'value' must be one of {sorted(VALUE_LEVELS)}")


def validate_source_evidence(finding: dict[str, Any], label: str, errors: list[str]) -> None:
    if not isinstance(finding.get("source"), dict):
        errors.append(f"{label}: 'source' must be an object")
    if not isinstance(finding.get("evidence"), list):
        errors.append(f"{label}: 'evidence' must be an array")


def validate_api(path: Path, errors: list[str]) -> None:
    data = require_object(load_json(path, errors), str(path), errors)
    if data is None:
        return
    for idx, item in enumerate(validate_common(data, "apis", path, errors), 1):
        label = f"{path}: apis[{idx - 1}]"
        finding = require_object(item, label, errors)
        if finding is None:
            continue
        missing = API_FIELDS - finding.keys()
        extra = finding.keys() - API_FIELDS
        if missing:
            errors.append(f"{label}: missing fields {sorted(missing)}")
        if extra:
            errors.append(f"{label}: unexpected fields {sorted(extra)}")
        validate_value(finding.get("value"), label, errors)
        validate_source_evidence(finding, label, errors)
        if not isinstance(finding.get("parameters"), list):
            errors.append(f"{label}: 'parameters' must be an array")
        if not isinstance(finding.get("headers"), list):
            errors.append(f"{label}: 'headers' must be an array")
        if not isinstance(finding.get("notes"), list):
            errors.append(f"{label}: 'notes' must be an array")


def validate_leak(path: Path, errors: list[str]) -> None:
    data = require_object(load_json(path, errors), str(path), errors)
    if data is None:
        return
    for idx, item in enumerate(validate_common(data, "leaks", path, errors), 1):
        label = f"{path}: leaks[{idx - 1}]"
        finding = require_object(item, label, errors)
        if finding is None:
            continue
        missing = LEAK_FIELDS - finding.keys()
        extra = finding.keys() - LEAK_FIELDS
        if missing:
            errors.append(f"{label}: missing fields {sorted(missing)}")
        if extra:
            errors.append(f"{label}: unexpected fields {sorted(extra)}")
        validate_value(finding.get("value"), label, errors)
        validate_source_evidence(finding, label, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ctf-web-js-analysis output files.")
    parser.add_argument("--directory", required=True, help="Directory containing information_api.json and information_leak.json.")
    args = parser.parse_args()

    directory = Path(args.directory)
    errors: list[str] = []
    validate_api(directory / "information_api.json", errors)
    validate_leak(directory / "information_leak.json", errors)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("ctf-web-js-analysis outputs are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
