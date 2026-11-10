"""Offline batch and Windows CMD integration tests; only synthetic PDFs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

from tools.pdf_batch import batch_convert
from tools.pdf_to_novel import analyse, validate_zip
from tests_pdf.test_pdf_to_novel import fixture


class BatchConversionTests(unittest.TestCase):
    def test_empty_folder_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            summary = batch_convert(folder / "PDFs", folder / "Novels", confirm_rights=True,
                                    report=lambda _: None)
            self.assertEqual(summary, {"found": 0, "converted": 0, "skipped": 0, "failed": 0})
            self.assertTrue((folder / "Novels").is_dir())

    def test_multiple_pdfs_and_existing_zip_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pdf_dir, novel_dir = folder / "PDFs", folder / "Novels"
            pdf_dir.mkdir()
            fixture(pdf_dir / "First Novel.PDF")
            fixture(pdf_dir / "Another novel.pdf", cover=False)
            outcomes = batch_convert(pdf_dir, novel_dir, confirm_rights=True, report=lambda _: None)
            self.assertEqual(outcomes["converted"], 2)
            outputs = sorted(novel_dir.glob("*.zip"))
            self.assertEqual(len(outputs), 2)
            self.assertEqual(len(list(novel_dir.glob("*-validation.json"))), 2)
            fingerprints = {p.name: p.read_bytes() for p in outputs}
            next_run = batch_convert(pdf_dir, novel_dir, confirm_rights=True, report=lambda _: None)
            self.assertEqual(next_run["skipped"], 2)
            self.assertEqual(next_run["converted"], 0)
            for path in outputs:
                self.assertEqual(path.read_bytes(), fingerprints[path.name])
                self.assertEqual(validate_zip(path)["chapter_count"], 2)

    def test_corrupt_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pdf_dir, novel_dir = folder / "PDFs", folder / "Novels"
            pdf_dir.mkdir()
            fixture(pdf_dir / "test.pdf")
            batch_convert(pdf_dir, novel_dir, confirm_rights=True, report=lambda _: None)
            zip_path = next(novel_dir.glob("*.zip"))
            damaged = b"not a zip"
            zip_path.write_bytes(damaged)
            summary = batch_convert(pdf_dir, novel_dir, confirm_rights=True, report=lambda _: None)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(zip_path.read_bytes(), damaged)

    def test_failed_pdf_does_not_block_another(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pdf_dir, novel_dir = folder / "PDFs", folder / "Novels"
            pdf_dir.mkdir()
            fixture(pdf_dir / "A broken numbering.pdf", gap=True)
            fixture(pdf_dir / "Z good.pdf")
            summary = batch_convert(pdf_dir, novel_dir, confirm_rights=True, report=lambda _: None)
            self.assertEqual((summary["failed"], summary["converted"]), (1, 1))
            self.assertEqual(len(list(novel_dir.glob("*.zip"))), 1)

    def test_manual_plan_applied_per_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pdf_dir, novel_dir = folder / "PDFs", folder / "Novels"
            pdf_dir.mkdir()
            pdf = pdf_dir / "planned.pdf"
            fixture(pdf)
            _, headings, _ = analyse(pdf)
            headings[1]["title"] = "2 VERIFIED EDITED TITLE"
            pdf.with_suffix(".chapters.json").write_text(
                json.dumps({"chapters": headings}), encoding="utf-8")
            result = batch_convert(pdf_dir, novel_dir, confirm_rights=True, report=lambda _: None)
            self.assertEqual(result["converted"], 1)
            with ZipFile(next(novel_dir.glob("*.zip"))) as archive:
                manifest = json.loads(next(archive.read(name) for name in archive.namelist()
                                           if name.endswith("/chapters.json")))
            self.assertEqual(manifest[1]["title"], "2 VERIFIED EDITED TITLE")

    def test_no_conversion_without_rights_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pdf_dir = folder / "PDFs"
            pdf_dir.mkdir()
            fixture(pdf_dir / "test.pdf")
            with self.assertRaisesRegex(ValueError, "permitted"):
                batch_convert(pdf_dir, folder / "Novels")
            self.assertFalse((folder / "Novels").exists())

    @unittest.skipUnless(os.name == "nt", "Windows CMD smoke test")
    def test_double_click_cmd_from_different_working_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            pdfs, novels = folder / "Input PDFs", folder / "Output Novels"
            pdfs.mkdir()
            fixture(pdfs / "My Book.pdf")
            cmd = Path(__file__).resolve().parents[1] / "PDF-to-Novel" / "Convert-PDFs.cmd"
            env = {**os.environ, "PDF_NOVEL_PDFS_DIR": str(pdfs),
                   "PDF_NOVEL_NOVELS_DIR": str(novels),
                   "PDF_NOVEL_ASSUME_RIGHTS": "1", "PDF_NOVEL_NO_PAUSE": "1"}
            for expected in ("converted", "already done"):
                run = subprocess.run(["cmd.exe", "/d", "/c", str(cmd)], cwd=temp,
                                     capture_output=True, text=True, errors="replace", env=env,
                                     timeout=120)
                self.assertEqual(run.returncode, 0, run.stdout + "\n" + run.stderr)
                self.assertIn(expected, run.stdout)
            self.assertEqual(len(list(novels.glob("*.zip"))), 1)
            self.assertEqual(validate_zip(next(novels.glob("*.zip")))["chapter_count"], 2)


if __name__ == "__main__":
    unittest.main()