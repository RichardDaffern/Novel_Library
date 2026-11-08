"""Offline-only tests for locally saved two-chapter WebNovel import."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from tools.webnovel_saved_pages import (
    SavedPageError, import_saved_pages, read_saved_chapter, main,
)

FIRST = (
    "<html><body><header><h1>Sample story</h1></header>"
    "<div class='cha-content'><p>Original chapter one passage with "
    "characters &amp; punctuation. The protagonist discovers a map "
    "and decides to travel.</p><p>Another original paragraph follows "
    "without any restricted content.</p></div></body></html>"
)
SECOND = (
    "<html><div class='chapter-content'><p>Original second chapter "
    "continues this invented story in a new setting near a lighthouse. "
    "The weather is calm and the characters talk.</p><p>"
    "The second paragraph remains entirely fictional.</p></div></html>"
)


class SavedPagesTests(unittest.TestCase):
    def _fixtures(self, root):
        p1, p2 = root / "one.html", root / "two.html"
        p1.write_text(FIRST, encoding="utf-8")
        p2.write_text(SECOND, encoding="utf-8")
        return p1, p2

    def test_two_html_pages_and_epub_order(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1, p2 = self._fixtures(root)
            out = root / "out"
            result = import_saved_pages(
                "Invented & Wonderful Story", "Original Author",
                [p1, p2], ["First <Day>", "Second Day"], out,
                confirm_rights=True,
            )
            self.assertEqual(result["chapter_count"], 2)
            self.assertEqual([c["position"] for c in result["chapters"]], [1, 2])
            self.assertEqual(result["title"], "Invented & Wonderful Story")
            self.assertEqual(result["author"], "Original Author")
            self.assertIn("Original chapter one", (out / "chapter-01.txt").read_text(encoding="utf-8"))
            self.assertIn("Original second chapter", (out / "chapter-02.txt").read_text(encoding="utf-8"))
            combined = (out / "book.txt").read_text(encoding="utf-8")
            self.assertLess(combined.index("Original chapter one"), combined.index("Original second chapter"))
            self.assertEqual(json.loads((out / "metadata.json").read_text(encoding="utf-8")), result)
            with ZipFile(out / "book.epub") as archive:
                self.assertIsNone(archive.testzip())
                ET.fromstring(archive.read("OEBPS/content.opf"))
                first = ET.fromstring(archive.read("OEBPS/chapter-01.xhtml"))
                second = ET.fromstring(archive.read("OEBPS/chapter-02.xhtml"))
                self.assertIn("Original chapter one", "".join(first.itertext()))
                self.assertIn("Original second chapter", "".join(second.itertext()))

    def test_plain_text_one_chapter(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "one.txt"
            p.write_text("An original paragraph about a mountain village. " * 4, encoding="utf-8")
            result = import_saved_pages(
                "Example", "Writer", [p], ["The Beginning"],
                root / "out", confirm_rights=True,
            )
            self.assertEqual(result["chapter_count"], 1)

    def test_mixed_formats(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1, _ = self._fixtures(root)
            p2 = root / "two.txt"
            p2.write_text("Second entirely original chapter text. " * 5, encoding="utf-8")
            result = import_saved_pages(
                "Example", "Writer", [p1, p2], ["First", "Second"],
                root / "out", confirm_rights=True,
            )
            self.assertEqual(result["chapter_count"], 2)

    def test_rights_required_before_reading(self):
        with patch("tools.webnovel_saved_pages.read_saved_chapter") as read:
            with self.assertRaisesRegex(SavedPageError, "confirm-rights"):
                import_saved_pages("Example", "Writer", ["one.html"], ["First"], "out")
            read.assert_not_called()

    def test_rejects_same_file_twice(self):
        with TemporaryDirectory() as tmp:
            p1, _ = self._fixtures(Path(tmp))
            with self.assertRaisesRegex(SavedPageError, "distinct"):
                import_saved_pages(
                    "Example", "Writer", [p1, p1], ["First", "Second"],
                    Path(tmp) / "out", confirm_rights=True,
                )

    def test_unsupported_extension(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "book.pdf"
            p.write_text("Wrong content", encoding="utf-8")
            with self.assertRaisesRegex(SavedPageError, "Unsupported"):
                read_saved_chapter(p, "First")

    def test_locked_saved_html_does_not_generate_output(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1, p2 = self._fixtures(root)
            p2.write_text("<html>Unlock this chapter</html>", encoding="utf-8")
            out = root / "out"
            with self.assertRaisesRegex(SavedPageError, "locked"):
                import_saved_pages(
                    "Example", "Writer", [p1, p2], ["First", "Second"],
                    out, confirm_rights=True,
                )
            self.assertFalse(out.exists())

    def test_missing_content_is_an_error(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "blank.html"
            p.write_text("<html><h1>Story title only</h1></html>", encoding="utf-8")
            with self.assertRaisesRegex(SavedPageError, "selector"):
                read_saved_chapter(p, "Chapter 1")

    def test_rejects_three_chapters(self):
        with self.assertRaisesRegex(SavedPageError, "one or two"):
            import_saved_pages("Example", "Writer", ["a", "b", "c"],
                               ["A", "B", "C"], "out", confirm_rights=True)

    def test_cli_success_and_no_network_calls(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1, p2 = self._fixtures(root)
            with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                rc = main([
                    "--book-title", "Example", "--author", "Writer",
                    "--chapter-1", str(p1), "--chapter-2", str(p2),
                    "--chapter-1-title", "One", "--chapter-2-title", "Two",
                    "--output-dir", str(root / "out"), "--confirm-rights",
                ])
            self.assertEqual(rc, 0)
            self.assertTrue((root / "out" / "book.epub").exists())


if __name__ == "__main__":
    unittest.main()
