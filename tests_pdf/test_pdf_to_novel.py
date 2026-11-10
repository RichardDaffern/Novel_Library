"""Fully offline PDF novel conversion regression tests (synthetic text only)."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import fitz
from PIL import Image

from tools.pdf_to_novel import ConversionError, analyse, convert, validate_zip


def fixture(path, *, cover=True, gap=False):
    doc = fitz.open()
    if cover:
        page = doc.new_page(width=400, height=600)
        stream = BytesIO()
        Image.new("RGB", (400, 600), (18, 46, 76)).save(stream, format="PNG")
        page.insert_image(fitz.Rect(0, 0, 400, 600), stream=stream.getvalue())
    for chapter in range(1, 3):
        page = doc.new_page(width=400, height=600)
        number = 4 if gap and chapter == 2 else chapter
        page.insert_text((50, 45), f"{number} CHAPTER {number} TITLE", fontname="hebo", fontsize=17)
        page.insert_text((65, 85), f"First paragraph in chapter {chapter} begins here.", fontsize=11)
        page.insert_text((50, 105), "Continuation at the same indentation.", fontsize=11)
        page.insert_text((65, 132), "An international line with Café Ω 中文 is retained.", fontsize=11)
        page.insert_text((50, 150), "This line ends with a hyphen-", fontsize=11)
        page.insert_text((50, 167), "joined noun follows the hyphen.", fontsize=11)
    doc.set_metadata({"title": "Synthetic Original Story", "author": "Test Author"})
    doc.save(path)
    doc.close()


class ConverterTests(unittest.TestCase):
    def test_detect_and_convert_zip_with_epub_cover_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "test.pdf"
            fixture(source)
            pdf_bytes = source.read_bytes()
            pages, heads, report = analyse(source)
            self.assertEqual([x["number"] for x in heads], [1, 2])
            self.assertEqual(report["front_matter_pages"], 1)
            target, report_file = convert(source, root / "output", expected_chapters=2, progress=lambda _: None)
            result = validate_zip(target, 2)
            self.assertEqual(result["status"], "passed")
            with ZipFile(target) as archive:
                prefix = "synthetic-original-story/"
                self.assertIn(prefix + "cover.jpg", archive.namelist())
                rows = json.loads(archive.read(prefix + "chapters.json"))
                body = archive.read(prefix + "chapter_0001.txt").decode("utf-8")
                self.assertEqual(rows[0]["position"], 1)
                self.assertEqual(rows[1]["chapter_number"], 2)
                self.assertIn("Café", body)
                self.assertIn("First paragraph in chapter 1 begins here. Continuation", body)
                self.assertIn("hyphen-joined", body)
                with ZipFile(BytesIO(archive.read(prefix + "source.epub"))) as epub:
                    self.assertIn("OEBPS/cover.jpg", epub.namelist())
                    self.assertIn("OEBPS/chap000002.xhtml", epub.namelist())
            self.assertEqual(source.read_bytes(), pdf_bytes)
            summary = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(summary["body_lines_expected"], summary["body_lines_emitted"])

    def test_duplicate_or_missing_chapters_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "gapped.pdf"
            fixture(src, gap=True)
            with self.assertRaisesRegex(ConversionError, "Missing, duplicate"):
                analyse(src)

    def test_expected_count_failure_does_not_publish_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "test.pdf"
            fixture(src)
            with self.assertRaisesRegex(ConversionError, "Expected 3"):
                convert(src, root / "out", expected_chapters=3, progress=lambda _: None)
            self.assertFalse(list((root / "out").glob("*.zip")) if (root / "out").exists() else False)

    def test_existing_zip_must_not_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "test.pdf"
            fixture(src)
            first, _ = convert(src, root / "out", progress=lambda _: None)
            baseline = first.read_bytes()
            with self.assertRaisesRegex(ConversionError, "overwrite"):
                convert(src, root / "out", progress=lambda _: None)
            self.assertEqual(first.read_bytes(), baseline)
            convert(src, root / "out", replace=True, progress=lambda _: None)
            self.assertTrue(first.is_file())

    def test_manual_heading_overrides_and_reports_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "test.pdf"
            fixture(src)
            plan = root / "plan.json"
            _, heads, _ = analyse(src)
            heads[1]["title"] = "2 REVIEWED CORRECTED TITLE"
            plan.write_text(json.dumps({"chapters": heads}), encoding="utf-8")
            target, report_file = convert(src, root / "out", boundaries=plan, progress=lambda _: None)
            with ZipFile(target) as archive:
                items = json.loads(archive.read("synthetic-original-story/chapters.json"))
                self.assertEqual(items[1]["title"], heads[1]["title"])
            report = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(len(report["manual_heading_corrections"]), 1)

    def test_manually_provided_duplicate_markers_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "test.pdf"
            fixture(src)
            _, heads, _ = analyse(src)
            heads[1] = dict(heads[0])
            plan = root / "plan.json"
            plan.write_text(json.dumps({"chapters": heads}), encoding="utf-8")
            with self.assertRaisesRegex(ConversionError, "Duplicated or unordered"):
                analyse(src, plan)

    def test_image_only_input_needs_ocr_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.pdf"
            pdf = fitz.open()
            pdf.new_page()
            pdf.save(path)
            pdf.close()
            with self.assertRaisesRegex(ConversionError, "selectable text"):
                analyse(path)

    def test_corrupted_zip_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "test.pdf"
            fixture(src)
            target, _ = convert(src, root / "out", progress=lambda _: None)
            with ZipFile(target) as archive:
                data = {name: archive.read(name) for name in archive.namelist()}
            data["synthetic-original-story/chapter_0001.txt"] = b"Tampered\n"
            with ZipFile(target, "w") as archive:
                for filename, payload in data.items():
                    archive.writestr(filename, payload)
            with self.assertRaises(ConversionError):
                validate_zip(target)


if __name__ == "__main__":
    unittest.main()