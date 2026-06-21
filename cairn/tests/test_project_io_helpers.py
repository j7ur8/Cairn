from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class SafeFilenameTests(unittest.TestCase):
    def test_strips_directory_components(self) -> None:
        from cairn.server.application.project_io import _safe_filename

        self.assertEqual(_safe_filename("/etc/passwd"), "passwd")
        self.assertEqual(_safe_filename("../../secret.txt"), "secret.txt")

    def test_replaces_unsafe_characters(self) -> None:
        from cairn.server.application.project_io import _safe_filename

        out = _safe_filename("a;b|c&d.txt")
        self.assertNotIn(";", out)
        self.assertNotIn("|", out)
        self.assertNotIn("&", out)
        self.assertTrue(out.endswith(".txt"))

    def test_strips_null_bytes(self) -> None:
        from cairn.server.application.project_io import _safe_filename

        self.assertNotIn("\x00", _safe_filename("evil\x00.txt"))

    def test_empty_or_dotty_falls_back_to_attachment(self) -> None:
        from cairn.server.application.project_io import _safe_filename

        self.assertEqual(_safe_filename(""), "attachment")
        self.assertEqual(_safe_filename("..."), "attachment")
        self.assertEqual(_safe_filename("   "), "attachment")

    def test_truncates_overlong_names(self) -> None:
        from cairn.server.application.project_io import _safe_filename

        self.assertLessEqual(len(_safe_filename("a" * 500 + ".txt")), 180)


class DedupePathTests(unittest.TestCase):
    def test_flattens_separators_into_project_dir(self) -> None:
        from cairn.server.application.project_io import _dedupe_path

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            result = _dedupe_path(project_dir, "sub/dir/file.txt")
            # Separators are collapsed; the file stays directly under project_dir.
            self.assertEqual(result.parent, project_dir.resolve())

    def test_rejects_escape_attempt(self) -> None:
        from cairn.server.application.project_io import _dedupe_path

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "proj"
            project_dir.mkdir()
            # Slash/backslash separators are collapsed to underscores, so even a
            # traversal-shaped name can never resolve outside the project dir.
            result = _dedupe_path(project_dir, "....//....//etc")
            self.assertTrue(
                str(result.resolve()).startswith(str(project_dir.resolve())),
                f"{result} escaped {project_dir}",
            )

    def test_dedupes_existing_filename(self) -> None:
        from cairn.server.application.project_io import _dedupe_path

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            (project_dir / "report.txt").write_text("x", encoding="utf-8")
            result = _dedupe_path(project_dir, "report.txt")
            self.assertEqual(result.name, "report-1.txt")

            (project_dir / "report-1.txt").write_text("x", encoding="utf-8")
            result2 = _dedupe_path(project_dir, "report.txt")
            self.assertEqual(result2.name, "report-2.txt")


class CategoryTests(unittest.TestCase):
    def test_attachment_source_is_attachments(self) -> None:
        from cairn.server.application.project_io import _category

        self.assertEqual(_category("attachment", "anything.txt"), "attachments")

    def test_reports_prefix(self) -> None:
        from cairn.server.application.project_io import _category

        self.assertEqual(_category("project", "reports/final.md"), "reports")

    def test_exploit_prefixes(self) -> None:
        from cairn.server.application.project_io import _category

        self.assertEqual(_category("project", "exploit/poc.py"), "exploit")
        self.assertEqual(_category("project", "vuln-research/notes.md"), "exploit")

    def test_other_default(self) -> None:
        from cairn.server.application.project_io import _category

        self.assertEqual(_category("project", "misc/scratch.txt"), "other")
        self.assertEqual(_category("project", ""), "other")


class AttachmentHintTests(unittest.TestCase):
    def test_uses_description_when_present(self) -> None:
        from cairn.server.application.project_io import _attachment_hint

        hint = _attachment_hint("登录截图", "/work/proj/shot.png")
        self.assertIn("登录截图", hint)
        self.assertIn("/work/proj/shot.png", hint)

    def test_falls_back_when_description_blank(self) -> None:
        from cairn.server.application.project_io import _attachment_hint

        hint = _attachment_hint("   ", "/work/proj/shot.png")
        self.assertIn("附件", hint)
        self.assertIn("/work/proj/shot.png", hint)


class CleanupPathsTests(unittest.TestCase):
    def test_unlinks_existing_and_ignores_missing(self) -> None:
        from cairn.server.application.project_io import cleanup_paths

        with tempfile.TemporaryDirectory() as td:
            present = Path(td) / "a.txt"
            present.write_text("x", encoding="utf-8")
            missing = Path(td) / "gone.txt"
            # Should not raise on the missing path.
            cleanup_paths([present, missing])
            self.assertFalse(present.exists())


class PrepareProjectStorageTests(unittest.TestCase):
    def test_clears_existing_project_files_and_attachments(self) -> None:
        from cairn.server.application.project_io import prepare_project_storage
        from helpers import TempYamlConfig

        with TempYamlConfig() as cfg:
            project_root = Path(cfg.written_server["server"]["paths"]["project_files_root"])
            attachments_root = Path(cfg.written_server["server"]["paths"]["attachments_root"])
            project_dir = project_root / "proj_clean"
            attachment_dir = attachments_root / "proj_clean"
            (project_dir / "reports").mkdir(parents=True)
            (project_dir / "reports" / "old.md").write_text("old", encoding="utf-8")
            attachment_dir.mkdir(parents=True)
            (attachment_dir / "file.zip").write_text("old", encoding="utf-8")

            prepare_project_storage("proj_clean")

            self.assertEqual(list(project_dir.iterdir()), [])
            self.assertEqual(list(attachment_dir.iterdir()), [])

    def test_creates_missing_project_storage_dirs(self) -> None:
        from cairn.server.application.project_io import prepare_project_storage
        from helpers import TempYamlConfig

        with TempYamlConfig() as cfg:
            project_root = Path(cfg.written_server["server"]["paths"]["project_files_root"])
            attachments_root = Path(cfg.written_server["server"]["paths"]["attachments_root"])

            prepare_project_storage("proj_missing")

            self.assertTrue((project_root / "proj_missing").is_dir())
            self.assertTrue((attachments_root / "proj_missing").is_dir())
            self.assertEqual(list((project_root / "proj_missing").iterdir()), [])
            self.assertEqual(list((attachments_root / "proj_missing").iterdir()), [])

    def test_replaces_file_and_symlink_targets_with_directories(self) -> None:
        from cairn.server.application.project_io import prepare_project_storage
        from helpers import TempYamlConfig

        with TempYamlConfig() as cfg:
            project_root = Path(cfg.written_server["server"]["paths"]["project_files_root"])
            attachments_root = Path(cfg.written_server["server"]["paths"]["attachments_root"])
            project_root.mkdir(parents=True)
            attachments_root.mkdir(parents=True)
            (project_root / "proj_replace").write_text("old", encoding="utf-8")
            outside = Path(cfg.root) / "outside"
            outside.mkdir()
            (attachments_root / "proj_replace").symlink_to(outside, target_is_directory=True)

            prepare_project_storage("proj_replace")

            self.assertTrue((project_root / "proj_replace").is_dir())
            self.assertTrue((attachments_root / "proj_replace").is_dir())
            self.assertFalse((attachments_root / "proj_replace").is_symlink())
            self.assertTrue(outside.is_dir())

    def test_rejects_invalid_project_id(self) -> None:
        from fastapi import HTTPException

        from cairn.server.application.project_io import prepare_project_storage

        with self.assertRaises(HTTPException):
            prepare_project_storage("../escape")


if __name__ == "__main__":
    unittest.main()
