from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_js_guardrails() -> None:
    subprocess.run(
        ["node", "scripts/check_frontend.mjs"],
        cwd=ROOT,
        check=True,
    )
