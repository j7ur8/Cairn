#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


SCRIPT_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
LINK_RE = re.compile(r"""<link[^>]+(?:href)=["']([^"']+)["'][^>]*(?:rel=["'](?:modulepreload|preload)["'])?""", re.I)
IMPORT_RE = re.compile(r"""(?:import\(|importScripts\(|new\s+Worker\()\s*["']([^"']+)["']""")
SOURCEMAP_RE = re.compile(r"""sourceMappingURL=([^\s*]+)""")
JS_URL_RE = re.compile(r"""["'`](/?[^"'`\s<>]+?\.(?:m?js|js\.map)(?:\?[^"'`\s<>]*)?)["'`]""", re.I)


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def add(found: dict[str, dict[str, Any]], raw_url: str, base_url: str | None, source: str, confidence: str) -> None:
    raw_url = raw_url.strip()
    if not raw_url or raw_url.startswith(("data:", "blob:", "javascript:")):
        return
    url = urljoin(base_url or "", raw_url)
    item = found.setdefault(
        url,
        {
            "url": url,
            "sources": [],
            "confidence": confidence,
        },
    )
    if source not in item["sources"]:
        item["sources"].append(source)
    if item["confidence"] != "high" and confidence == "high":
        item["confidence"] = "high"


def extract_har(path: Path, found: dict[str, dict[str, Any]], base_url: str | None) -> bool:
    try:
        data = json.loads(load_text(path))
    except json.JSONDecodeError:
        return False
    entries = data.get("log", {}).get("entries", []) if isinstance(data, dict) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") or {}
        url = request.get("url")
        mime = ((entry.get("response") or {}).get("content") or {}).get("mimeType", "")
        if isinstance(url, str) and (".js" in url or "javascript" in str(mime)):
            add(found, url, base_url, str(path), "high")
    return bool(entries)


def extract_json(path: Path, found: dict[str, dict[str, Any]], base_url: str | None) -> bool:
    try:
        data = json.loads(load_text(path))
    except json.JSONDecodeError:
        return False

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and re.search(r"\.(?:m?js|js\.map)(?:[?#].*)?$", value, re.I):
            add(found, value, base_url, str(path), "medium")

    walk(data)
    return True


def extract_text(path: Path, found: dict[str, dict[str, Any]], base_url: str | None) -> None:
    text = load_text(path)
    for pattern, confidence in (
        (SCRIPT_RE, "high"),
        (LINK_RE, "medium"),
        (IMPORT_RE, "medium"),
        (SOURCEMAP_RE, "medium"),
        (JS_URL_RE, "medium"),
    ):
        for match in pattern.findall(text):
            add(found, match, base_url, str(path), confidence)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect JavaScript URLs from HTML, HAR, JSON, maps, service workers, and JS.")
    parser.add_argument("inputs", nargs="+", help="Input files to parse.")
    parser.add_argument("--base-url", default=None, help="Base URL for resolving relative paths.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    args = parser.parse_args()

    found: dict[str, dict[str, Any]] = {}
    for raw in args.inputs:
        path = Path(raw)
        if not path.exists() or not path.is_file():
            continue
        if extract_har(path, found, args.base_url):
            continue
        extract_json(path, found, args.base_url)
        extract_text(path, found, args.base_url)

    output = sorted(found.values(), key=lambda item: item["url"])
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
