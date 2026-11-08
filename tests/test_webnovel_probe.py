"""Offline tests for a metadata-only WebNovel feasibility probe.

These tests use invented book titles and never download or retain chapters.
"""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.webnovel_probe import (
    WebNovelProbeError, main, parse_public_book_metadata,
    probe_public_book, validate_book_url,
)

BOOK_URL = "https://www.webnovel.com/book/22196546206090805"
HTML = """<!DOCTYPE html><html><head><title>Invented Story - WebNovel</title>
<meta property="og:title" content="Invented Story - WebNovel"></head>
<body><h1>Invented Story</h1><div>Fantasy</div>
<div>3,151 Chapters 113.0M Views</div><p>Author: Invented Writer</p>
<div>4.71 (7,106 ratings)</div><h2>Synopsis</h2>
<p>Public metadata only. Chapter contents are not requested.</p>
</body></html>"""


class FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self.url

    def read(self, size):
        return self.text.encode("utf-8")[:size]


class WebNovelMetadataProbeTests(unittest.TestCase):
    def test_accepts_only_public_book_urls(self):
        self.assertEqual(
            validate_book_url("https://webnovel.com/book/22196546206090805"),
            BOOK_URL,
        )
        self.assertEqual(
            validate_book_url("https://www.webnovel.com/book/invented-story_22196546206090805"),
            "https://www.webnovel.com/book/invented-story_22196546206090805",
        )
        for url in (
            "http://www.webnovel.com/book/22196546206090805",
            "https://webnovel.com.evil.example/book/22196546206090805",
            "https://www.webnovel.com/",
            "https://www.webnovel.com/chapter/22196546206090805",
            "https://www.webnovel.com/book/22196546206090805?auth=token",
            "https://username:pass@www.webnovel.com/book/22196546206090805",
            "https://www.webnovel.com:8443/book/22196546206090805",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises((WebNovelProbeError, ValueError)):
                validate_book_url(url)

    def test_parse_title_author_and_chapter_count_only(self):
        result = parse_public_book_metadata(HTML, BOOK_URL)
        self.assertEqual(result["title"], "Invented Story")
        self.assertEqual(result["author"], "Invented Writer")
        self.assertEqual(result["listed_chapters"], 3151)
        self.assertFalse(result["chapter_text_extracted"])
        self.assertFalse(result["chapter_export_verified"])
        self.assertNotIn("chapters", result)

    def test_og_title_fallback_and_unknown_count(self):
        html = """<html><head><meta property="og:title" content="Example - WebNovel"/></head>
        <body><p>Author: Creator</p></body></html>"""
        result = parse_public_book_metadata(html, BOOK_URL)
        self.assertEqual(result["title"], "Example")
        self.assertIsNone(result["listed_chapters"])

    def test_missing_title_fails_loudly(self):
        with self.assertRaisesRegex(WebNovelProbeError, "title"):
            parse_public_book_metadata("<html><body>nothing</body></html>", BOOK_URL)

    def test_network_probe_only_requests_public_book_metadata(self):
        with patch("tools.webnovel_probe.urlopen", return_value=FakeResponse(BOOK_URL, HTML)) as request:
            result = probe_public_book(BOOK_URL)
        self.assertEqual(result["listed_chapters"], 3151)
        self.assertEqual(request.call_count, 1)
        requested_url = request.call_args.args[0].full_url
        self.assertEqual(requested_url, BOOK_URL)
        self.assertNotIn("/chapter/", requested_url)

    def test_redirect_to_different_book_is_rejected(self):
        wrong = "https://www.webnovel.com/book/12345678912345678"
        with patch("tools.webnovel_probe.urlopen", return_value=FakeResponse(wrong, HTML)):
            with self.assertRaisesRegex(WebNovelProbeError, "Redirected"):
                probe_public_book(BOOK_URL)

    def test_cli_can_parse_local_fixture_without_network(self):
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "book.html"
            fixture.write_text(HTML, encoding="utf-8")
            with patch("tools.webnovel_probe.urlopen") as request:
                with patch("sys.stdout", new_callable=io.StringIO) as output:
                    exit_code = main([BOOK_URL, "--html-file", str(fixture)])
            self.assertEqual(exit_code, 0)
            self.assertFalse(request.called)
            self.assertEqual(json.loads(output.getvalue())["title"], "Invented Story")


if __name__ == "__main__":
    unittest.main()
