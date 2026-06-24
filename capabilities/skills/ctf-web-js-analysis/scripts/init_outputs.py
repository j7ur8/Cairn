#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize ctf-web-js-analysis output files.")
    parser.add_argument("--directory", required=True, help="Directory where output JSON files will be written.")
    parser.add_argument("--target", default=None, help="Optional target URL or challenge identifier.")
    args = parser.parse_args()

    out_dir = Path(args.directory)
    common = {
        "schema_version": "1.0",
        "target": args.target,
        "generated_at": now(),
        "tool": "ctf-web-js-analysis",
        "notes": [],
    }
    write_json(out_dir / "information_api.json", {**common, "apis": []})
    write_json(out_dir / "information_leak.json", {**common, "leaks": []})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
