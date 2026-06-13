"""Tests for the path security helpers used by the files / attachments routers.

Covers:
  * project id format validation
  * relative path format validation (no traversal, no absolute)
  * safe_resolve_within refuses symlink escapes
  * download size cap is enforced
  * force_attachment_disposition picks attachment for HTML / SVG
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class ProjectIdValidatorTests(unittest.TestCase):
    def test_accepts_canonical_id(self) -> None:
        from cairn.server.security.paths import validate_project_id
        self.assertEqual(validate_project_id("proj_001"), "proj_001")

    def test_rejects_wrong_prefix(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import validate_project_id
        with self.assertRaises(HTTPException):
            validate_project_id("p_001")
        with self.assertRaises(HTTPException):
            validate_project_id("../escape")

    def test_rejects_empty(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import validate_project_id
        with self.assertRaises(HTTPException):
            validate_project_id("")


class RelativePathValidatorTests(unittest.TestCase):
    def test_accepts_normal_path(self) -> None:
        from cairn.server.security.paths import validate_relative_path
        rel = validate_relative_path("reports/run-1/output.json")
        self.assertEqual(rel.parts, ("reports", "run-1", "output.json"))

    def test_rejects_absolute_path(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import validate_relative_path
        with self.assertRaises(HTTPException):
            validate_relative_path("/etc/passwd")

    def test_rejects_parent_traversal(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import validate_relative_path
        with self.assertRaises(HTTPException):
            validate_relative_path("../escape")

    def test_dot_segments_are_silently_normalized(self) -> None:
        # PurePosixPath collapses ``.`` segments; the validator still
        # accepts the resulting clean path. The real defense against
        # traversal lives in safe_resolve_within, which is the next
        # layer in the lookup chain.
        from cairn.server.security.paths import validate_relative_path
        rel = validate_relative_path("a/./b")
        self.assertEqual(rel.parts, ("a", "b"))

    def test_rejects_empty(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import validate_relative_path
        with self.assertRaises(HTTPException):
            validate_relative_path("")


class SafeResolveWithinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj_001"
        self.root.mkdir(parents=True)
        (self.root / "ok.txt").write_text("hello")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "child.txt").write_text("child")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolves_existing_file(self) -> None:
        from cairn.server.security.paths import safe_resolve_within, validate_relative_path
        target = safe_resolve_within(self.root, validate_relative_path("ok.txt"))
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), "hello")

    def test_404_for_missing_file(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import safe_resolve_within, validate_relative_path
        with self.assertRaises(HTTPException) as ctx:
            safe_resolve_within(self.root, validate_relative_path("missing.txt"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_refuses_symlink_escape(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import safe_resolve_within, validate_relative_path
        # Symlink that points outside the project root
        external = Path(self.tmp.name) / "secret.txt"
        external.write_text("secret")
        (self.root / "leak.txt").symlink_to(external)
        with self.assertRaises(HTTPException):
            safe_resolve_within(self.root, validate_relative_path("leak.txt"))


class DownloadSizeGuardTests(unittest.TestCase):
    def test_allows_small_file(self) -> None:
        from cairn.server.security.paths import download_size_guard
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 100)
            f.flush()
            download_size_guard(Path(f.name), max_bytes=1024)
        os.unlink(f.name)

    def test_rejects_oversize(self) -> None:
        from fastapi import HTTPException

        from cairn.server.security.paths import download_size_guard
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 2048)
            f.flush()
            with self.assertRaises(HTTPException) as ctx:
                download_size_guard(Path(f.name), max_bytes=1024)
            self.assertEqual(ctx.exception.status_code, 413)
        os.unlink(f.name)


class DangerousMimeTests(unittest.TestCase):
    def test_html_is_dangerous(self) -> None:
        from cairn.server.security.paths import (
            force_attachment_disposition,
            is_dangerous_mime,
        )
        self.assertTrue(is_dangerous_mime("text/html"))
        self.assertTrue(is_dangerous_mime("text/html; charset=utf-8"))
        self.assertEqual(force_attachment_disposition("text/html"), "attachment")

    def test_svg_is_dangerous(self) -> None:
        from cairn.server.security.paths import is_dangerous_mime
        self.assertTrue(is_dangerous_mime("image/svg+xml"))

    def test_png_is_safe(self) -> None:
        from cairn.server.security.paths import (
            force_attachment_disposition,
            is_dangerous_mime,
        )
        self.assertFalse(is_dangerous_mime("image/png"))
        self.assertEqual(force_attachment_disposition("image/png"), "inline")
