#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_sourcemap(path: Path) -> bool:
    if path.suffix == ".map":
        return True
    try:
        tail = path.read_text(encoding="utf-8", errors="replace")[-4096:]
    except OSError:
        return False
    return "sourceMappingURL=" in tail


def classify(path: Path) -> str:
    lower = str(path).lower()
    if lower.endswith(".map"):
        return "source_map"
    if any(token in lower for token in ("vendor", "node_modules", "jquery", "react", "vue", "angular")):
        return "third_party"
    if any(token in lower for token in ("waf", "captcha", "risk", "rs", "ruishu", "debug", "fingerprint")):
        return "defensive_js"
    if lower.endswith((".json", ".webmanifest")):
        return "config"
    if lower.endswith((".js", ".mjs")):
        return "business_js"
    return "unknown"


def load_urls(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, Any]] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                result[item["url"]] = item
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a normalized JavaScript inventory.")
    parser.add_argument("--root", required=True, help="Directory containing downloaded JS artifacts.")
    parser.add_argument("--urls", default=None, help="Optional JSON list produced by collect_js_urls.py.")
    parser.add_argument("--output", required=True, help="Output inventory JSON path.")
    args = parser.parse_args()

    root = Path(args.root)
    url_items = load_urls(Path(args.urls) if args.urls else None)
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".js", ".mjs", ".map", ".json", ".webmanifest"}
    ]
    inventory: list[dict[str, Any]] = []
    for path in sorted(files):
        rel = path.relative_to(root).as_posix()
        matched_url = None
        matched_meta: dict[str, Any] = {}
        for url, meta in url_items.items():
            if url.endswith(rel) or Path(url.split("?", 1)[0]).name == path.name:
                matched_url = url
                matched_meta = meta
                break
        inventory.append(
            {
                "url": matched_url,
                "local_path": str(path),
                "relative_path": rel,
                "sha256": sha256_file(path),
                "source": matched_meta.get("sources", []),
                "confidence": matched_meta.get("confidence", "local_file"),
                "type": classify(path),
                "has_sourcemap": has_sourcemap(path),
            }
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"schema_version": "1.0", "items": inventory}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
