"""Synthetic-only regression tests for capped public WebNovel adapter."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools.webnovel_public_two_chapter import (
    PublicChapterError, public_first_two_links, parse_public_chapter,
    probe_two_chapters, _chapter_url,
)

BOOK = "https://www.webnovel.com/book/33422293300201205"
CH1 = "https://www.webnovel.com/book/story_33422293300201205/first_89735050081387238"
CH2 = "https://www.webnovel.com/book/story_33422293300201205/second_89735050081387259"

BOOK_HTML = f"""<html><h1>Original Test Story</h1><div>Author: Example Writer 2 Chapters</div>
<a href="{CH1}">1 Chapter 1: First Day</a>
<a href="{CH2}">2 Chapter 2: Next Day</a>
<a href="/book/story_33422293300201205/third_89735050081387260">3 Chapter 3: Never Fetch</a>
</html>"""
FIRST = """<html><div class="cha-content"><p>First invented chapter passage with enough text for safe offline checking.</p>
<p>A second entirely synthetic paragraph is present.</p></div></html>"""
SECOND = """<html><div class="cha-content"><p>Second invented chapter passage with enough text for safe offline checking.</p>
<p>The second synthetic chapter is after the first.</p></div></html>"""


class PublicTwoChapterTests(unittest.TestCase):
    def test_public_catalogue_first_two_only(self):
        links = public_first_two_links(BOOK_HTML, BOOK)
        self.assertEqual([u for u, _ in links], [CH1, CH2])

    def test_rejects_other_domains_books_and_queries(self):
        for url in (
            CH1.replace("www.webnovel.com", "webnovel.com.evil.test"),
            CH1.replace("33422293300201205", "11111111111111111"),
            CH1 + "?token=abc",
            CH1.replace("https:", "http:"),
        ):
            with self.subTest(url=url), self.assertRaises(PublicChapterError):
                _chapter_url(url, "33422293300201205")

    def test_rejects_missing_catalogue_chapters(self):
        with self.assertRaises(PublicChapterError):
            public_first_two_links("<html><h1>Story</h1></html>", BOOK)

    def test_rejects_locked_chapter(self):
        with self.assertRaisesRegex(PublicChapterError, "locked"):
            parse_public_chapter('<div class="cha-content">Unlock this chapter to continue reading</div>', CH1, "First")

    def test_rejects_unknown_layout(self):
        with self.assertRaisesRegex(PublicChapterError, "selector"):
            parse_public_chapter("<html><body>Test content without chapter container.</body></html>", CH1, "First")

    def test_no_requests_without_rights_confirmation(self):
        with patch("tools.webnovel_public_two_chapter.get_public_html") as fetch:
            with self.assertRaisesRegex(PublicChapterError, "confirm-rights"):
                probe_two_chapters(BOOK, "unused-output")
            fetch.assert_not_called()

    def test_two_chapter_export_and_three_request_ceiling(self):
        calls = []
        pages = {BOOK: BOOK_HTML, CH1: FIRST, CH2: SECOND}

        def fetch(url):
            calls.append(url)
            return pages[url]

        with TemporaryDirectory() as tmp:
            result = probe_two_chapters(BOOK, Path(tmp) / "out", confirm_rights=True, fetcher=fetch)
            self.assertEqual(calls, [BOOK, CH1, CH2])
            self.assertEqual(result["chapter_count"], 2)
            self.assertEqual(result["source"], "webnovel-public-with-user-confirmed-rights")
            out = Path(tmp) / "out"
            self.assertIn("First invented chapter", (out / "chapter-01.txt").read_text(encoding="utf-8"))
            self.assertIn("Second invented chapter", (out / "chapter-02.txt").read_text(encoding="utf-8"))
            with ZipFile(out / "book.epub") as epub:
                self.assertEqual(epub.testzip(), None)
                self.assertIn("OEBPS/chapter-02.xhtml", epub.namelist())

    def test_no_output_if_second_chapter_locked(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            pages = {BOOK: BOOK_HTML, CH1: FIRST, CH2: "<div>Unlock this chapter</div>"}
            with self.assertRaises(PublicChapterError):
                probe_two_chapters(BOOK, out, confirm_rights=True, fetcher=pages.__getitem__)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
