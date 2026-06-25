from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


_REPO = Path(__file__).resolve().parents[2]
_SCRIPT_DIR = _REPO / "capabilities" / "skills" / "ctf-web-js-analysis" / "scripts"
_INIT = _SCRIPT_DIR / "init_outputs.py"
_MERGE = _SCRIPT_DIR / "merge_api_leak_findings.py"
_VALIDATE = _SCRIPT_DIR / "validate_outputs.py"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(arg) for arg in args)],
        cwd=_REPO,
        text=True,
        capture_output=True,
        check=False,
    )


class CtfWebJsAnalysisScriptTests(unittest.TestCase):
    def test_init_outputs_validate_empty_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)

            init = _run(_INIT, "--directory", out_dir, "--target", "https://example.test")
            self.assertEqual(init.returncode, 0, init.stderr)

            validate = _run(_VALIDATE, "--directory", out_dir)
            self.assertEqual(validate.returncode, 0, validate.stderr)
            self.assertIn("outputs are valid", validate.stdout)

    def test_merge_accepts_new_schema_and_validator_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            findings = out_dir / "manual_findings.json"
            _write_json(
                findings,
                {
                    "apis": [
                        {
                            "id": "api-login",
                            "url": "/api/login",
                            "method": "POST",
                            "parameters": [{"name": "username", "location": "body", "required": None, "evidence": []}],
                            "headers": [],
                            "auth_context": "anonymous",
                            "source": {"type": "business_js", "url": "/app.js"},
                            "evidence": [{"kind": "static_match", "snippet": "fetch('/api/login')"}],
                            "value": "medium",
                            "notes": [],
                        }
                    ],
                    "leaks": [
                        {
                            "id": "leak-config",
                            "value": "high",
                            "type": "debug_config",
                            "source": {"type": "config", "url": "/config.js"},
                            "evidence": [{"kind": "static_match", "snippet": "debug=true"}],
                        }
                    ],
                },
            )

            merge = _run(_MERGE, "--tool-output", findings, "--output-dir", out_dir)
            self.assertEqual(merge.returncode, 0, merge.stderr)

            validate = _run(_VALIDATE, "--directory", out_dir)
            self.assertEqual(validate.returncode, 0, validate.stderr)

    def test_merge_default_scan_skips_inventory_json_and_uses_finding_files_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            _write_json(out_dir / "js_urls.json", [{"url": "/static/app.js", "source": "index.html"}])
            _write_json(
                out_dir / "js_inventory.json",
                {"items": [{"url": "/assets/chunk.js", "local_path": "chunk.js", "confidence": "high"}]},
            )
            _write_json(
                out_dir / "scanner_findings.json",
                {
                    "api_findings": [
                        {
                            "url": "/api/flag",
                            "method": "GET",
                            "source": {"type": "business_js", "url": "/app.js"},
                            "evidence": [{"kind": "static_match"}],
                            "value": "high",
                        }
                    ]
                },
            )

            merge = _run(_MERGE, "--artifact-dir", out_dir, "--output-dir", out_dir)
            self.assertEqual(merge.returncode, 0, merge.stderr)

            api_output = _read_json(out_dir / "information_api.json")
            self.assertEqual([api["url"] for api in api_output["apis"]], ["/api/flag"])

    def test_legacy_confidence_is_mapped_only_at_merge_input_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            legacy = out_dir / "legacy_tool_output.json"
            _write_json(
                legacy,
                {
                    "apis": [
                        {
                            "url": "/api/profile",
                            "method": "GET",
                            "source": {"type": "business_js"},
                            "evidence": [],
                            "confidence": "static_candidate",
                        }
                    ],
                    "leaks": [
                        {
                            "type": "debug_config",
                            "value_or_summary": "debug mode enabled",
                            "source": {"type": "config"},
                            "evidence": [],
                            "confidence": "static_high",
                        }
                    ],
                },
            )

            merge = _run(_MERGE, "--tool-output", legacy, "--output-dir", out_dir)
            self.assertEqual(merge.returncode, 0, merge.stderr)

            api_output = _read_json(out_dir / "information_api.json")
            leak_output = _read_json(out_dir / "information_leak.json")
            self.assertEqual(api_output["apis"][0]["value"], "low")
            self.assertNotIn("confidence", api_output["apis"][0])
            self.assertEqual(leak_output["leaks"][0]["value"], "low")
            self.assertNotIn("confidence", leak_output["leaks"][0])
            self.assertNotIn("value_or_summary", leak_output["leaks"][0])

            validate = _run(_VALIDATE, "--directory", out_dir)
            self.assertEqual(validate.returncode, 0, validate.stderr)

    def test_validator_rejects_legacy_final_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            common = {
                "schema_version": "1.0",
                "target": None,
                "generated_at": "2026-06-24T00:00:00Z",
                "tool": "ctf-web-js-analysis",
                "notes": [],
            }
            _write_json(out_dir / "information_api.json", {**common, "apis": []})
            _write_json(
                out_dir / "information_leak.json",
                {
                    **common,
                    "leaks": [
                        {
                            "type": "debug_config",
                            "value_or_summary": "debug mode enabled",
                            "source": {"type": "config"},
                            "evidence": [],
                            "confidence": "static_candidate",
                        }
                    ],
                },
            )

            validate = _run(_VALIDATE, "--directory", out_dir)
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("missing fields", validate.stderr)
            self.assertIn("unexpected fields", validate.stderr)

    def test_merge_preserves_invalid_explicit_value_for_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            findings = out_dir / "invalid_value_findings.json"
            _write_json(
                findings,
                {
                    "leak_findings": [
                        {
                            "type": "api_key",
                            "value": "critical",
                            "source": {"type": "config"},
                            "evidence": [],
                        }
                    ]
                },
            )

            merge = _run(_MERGE, "--tool-output", findings, "--output-dir", out_dir)
            self.assertEqual(merge.returncode, 0, merge.stderr)
            self.assertEqual(_read_json(out_dir / "information_leak.json")["leaks"][0]["value"], "critical")

            validate = _run(_VALIDATE, "--directory", out_dir)
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("'value' must be one of", validate.stderr)

    def test_missing_value_defaults_to_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            findings = out_dir / "missing_value_findings.json"
            _write_json(
                findings,
                {
                    "api_findings": [
                        {
                            "url": "/healthz",
                            "method": "GET",
                            "source": {"type": "business_js"},
                            "evidence": [],
                        }
                    ]
                },
            )

            merge = _run(_MERGE, "--tool-output", findings, "--output-dir", out_dir)
            self.assertEqual(merge.returncode, 0, merge.stderr)

            api_output = _read_json(out_dir / "information_api.json")
            self.assertEqual(api_output["apis"][0]["value"], "info")


if __name__ == "__main__":
    unittest.main()
