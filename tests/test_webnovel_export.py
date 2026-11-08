"""Offline regression tests for separate WebNovel-authorised export, no website access."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_STORED

from tools.webnovel_export import ExportError, export, main, validate


def sample():
    return {
        "source": "user-supplied-authorised",
        "title": "Example & Original Story",
        "author": "Test Writer",
        "chapters": [
            {"position": 1, "title": "First <Day>", "text": "This is an invented first chapter.\n\nIt has two paragraphs."},
            {"position": 2, "title": "Second Chapter", "text": "This is an invented second chapter.\n\nIt comes after the first."},
        ],
    }


class WebNovelExportTests(unittest.TestCase):
    def test_two_chapter_files_metadata_and_epub(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "export"
            manifest = export(sample(), out)
            self.assertEqual([c["position"] for c in manifest["chapters"]], [1, 2])
            self.assertEqual(manifest["title"], "Example & Original Story")
            self.assertEqual(manifest["author"], "Test Writer")
            self.assertEqual(manifest["chapter_count"], 2)
            self.assertEqual(json.loads((out / "metadata.json").read_text(encoding="utf-8")), manifest)
            self.assertIn("invented first chapter", (out / "chapter-01.txt").read_text(encoding="utf-8"))
            self.assertIn("invented second chapter", (out / "chapter-02.txt").read_text(encoding="utf-8"))
            text = (out / "book.txt").read_text(encoding="utf-8")
            self.assertLess(text.index("invented first chapter"), text.index("invented second chapter"))
            with ZipFile(out / "book.epub") as z:
                self.assertEqual(z.testzip(), None)
                self.assertEqual(z.namelist()[0], "mimetype")
                self.assertEqual(z.getinfo("mimetype").compress_type, ZIP_STORED)
                self.assertEqual(z.read("mimetype"), b"application/epub+zip")
                ET.fromstring(z.read("META-INF/container.xml"))
                opf = ET.fromstring(z.read("OEBPS/content.opf"))
                self.assertIn("Example & Original Story", "".join(opf.itertext()))
                ET.fromstring(z.read("OEBPS/toc.ncx"))
                first = ET.fromstring(z.read("OEBPS/chapter-01.xhtml"))
                second = ET.fromstring(z.read("OEBPS/chapter-02.xhtml"))
                self.assertIn("invented first chapter", "".join(first.itertext()))
                self.assertIn("invented second chapter", "".join(second.itertext()))
                self.assertEqual(len([n for n in z.namelist() if n.endswith(".xhtml")]), 2)

    def test_one_chapter_supported(self):
        data = sample()
        data["chapters"] = data["chapters"][:1]
        with TemporaryDirectory() as tmp:
            manifest = export(data, Path(tmp) / "out")
            self.assertEqual(manifest["chapter_count"], 1)

    def test_refuses_more_than_two_chapters(self):
        data = sample()
        data["chapters"].append({"position": 3, "title": "Third", "text": "Invented third chapter text"})
        with self.assertRaisesRegex(ExportError, "one or two"):
            validate(data)

    def test_refuses_missing_authorisation_marker(self):
        data = sample()
        data["source"] = "webnovel-scraped"
        with self.assertRaisesRegex(ExportError, "user-supplied-authorised"):
            validate(data)

    def test_refuses_reordered_chapters(self):
        data = sample()
        data["chapters"].reverse()
        with self.assertRaisesRegex(ExportError, "consecutive"):
            validate(data)

    def test_refuses_empty_body(self):
        data = sample()
        data["chapters"][0]["text"] = " "
        with self.assertRaises(ExportError):
            validate(data)

    def test_refuses_existing_nonempty_output(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "existing"
            out.mkdir()
            (out / "important.txt").write_text("keep")
            with self.assertRaisesRegex(ExportError, "empty"):
                export(sample(), out)
            self.assertEqual((out / "important.txt").read_text(), "keep")

    def test_cli_from_local_json(self):
        with TemporaryDirectory() as tmp:
            inp = Path(tmp) / "input.json"
            inp.write_text(json.dumps(sample()), encoding="utf-8")
            self.assertEqual(main(["--input", str(inp), "--output-dir", str(Path(tmp) / "out")]), 0)
            self.assertTrue((Path(tmp) / "out" / "book.epub").is_file())

    def test_cli_rejects_bad_json(self):
        with TemporaryDirectory() as tmp:
            inp = Path(tmp) / "bad.json"
            inp.write_text("not json", encoding="utf-8")
            self.assertEqual(main(["--input", str(inp), "--output-dir", str(Path(tmp) / "out")]), 1)


if __name__ == "__main__":
    unittest.main()
