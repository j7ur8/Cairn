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


def test_server_form_uses_multipart_endpoints() -> None:
    source = (ROOT / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-proxies.js").read_text(
        encoding="utf-8"
    )
    save = source.split("async saveServerResource()", 1)[1].split("async testServerResource", 1)[0]
    assert "new FormData()" in save
    assert "this.authFetch('/servers/add'" in save
    assert "method: 'POST'" in save
    assert "method: 'PUT'" in save
    assert "this.api('POST', '/servers'" not in save
    assert "auth_type" not in save
    assert "auth_order" not in save


def test_project_proxy_edit_does_not_submit_empty_password() -> None:
    source = (ROOT / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-proxies.js").read_text(
        encoding="utf-8"
    )
    save = source.split("async saveProjectProxy()", 1)[1].split("async deleteProjectProxy", 1)[0]
    assert "password: this.projectProxyForm.password || null" not in save
    assert "if (this.projectProxyForm.password?.trim())" in save
