"""Synthetic-only tests for visible-browser WebNovel public retrieval experiment."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools.webnovel_browser_probe import (
    BrowserProbeError, browser_probe, _checked_page, main
)

BOOK = "https://www.webnovel.com/book/33422293300201205"
CH1 = "https://www.webnovel.com/book/story_33422293300201205/first_89735050081387238"
CH2 = "https://www.webnovel.com/book/story_33422293300201205/second_89735050081387259"
CATALOG = f"""<html><h1>Original Example</h1>
<a href="{CH1}">1 Chapter 1: First Day</a>
<a href="{CH2}">2 Chapter 2: Second Day</a></html>"""
BODY1 = """<html><div class="cha-content"><p>Original chapter one in a quiet
    village with a well and a market. Characters meet near a small stone house
    and prepare for a long journey.</p></div></html>"""
BODY2 = """<html><div class="cha-content"><p>Original chapter two begins
    when the travellers reach the edge of the forest. They pause to discuss
    their map and decide where they should go next.</p></div></html>"""


class FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {}


class FakePage:
    def __init__(self, pages):
        self.pages = pages
        self.url = ""
        self.visited = []
        self.waits = []

    def goto(self, url, **options):
        self.url = url
        self.visited.append(url)
        value = self.pages.get(url)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            html, status, redirect, *extra = value
            if redirect:
                self.url = redirect
            self._current = html
            return FakeResponse(status, extra[0] if extra else None)
        self._current = value
        return FakeResponse() if value is not None else None

    def content(self):
        return self._current

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


class FakeContext:
    def __init__(self, pages):
        self.page = FakePage(pages)
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, pages):
        self.context = FakeContext(pages)
        self.closed = False

    def new_context(self):
        return self.context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, pages):
        self.browser = FakeBrowser(pages)
        self.launch_args = None

    def launch(self, **kwargs):
        self.launch_args = kwargs
        return self.browser


class BrowserTests(unittest.TestCase):
    def test_chapter_retrieval_and_epub_without_live_network(self):
        chromium = FakeChromium({BOOK: CATALOG, CH1: BODY1, CH2: BODY2})
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = browser_probe(BOOK, out, 'Original & Example', 'A Writer',
                                   confirm_rights=True, chromium=chromium)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK, CH1, CH2])
            self.assertFalse(chromium.launch_args['headless'])
            self.assertEqual(result['chapter_count'], 2)
            self.assertTrue(chromium.browser.closed)
            self.assertTrue(chromium.browser.context.closed)
            self.assertIn('Original chapter one', (out / 'chapter-01.txt').read_text(encoding='utf-8'))
            self.assertIn('Original chapter two', (out / 'chapter-02.txt').read_text(encoding='utf-8'))
            with ZipFile(out / 'book.epub') as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(len([n for n in archive.namelist() if n.endswith('.xhtml')]), 2)

    def test_rights_required_before_browser_launch(self):
        chromium = FakeChromium({})
        with self.assertRaisesRegex(BrowserProbeError, 'confirm-rights'):
            browser_probe(BOOK, 'unused', 'A', 'B', chromium=chromium)
        self.assertIsNone(chromium.launch_args)

    def test_cloudflare_challenge_stops_without_fetching_chapters(self):
        chromium = FakeChromium({
            BOOK: ('<html><title>Just a moment...</title><div>Verify you are human</div></html>', 200, None)
        })
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with self.assertRaisesRegex(BrowserProbeError, 'challenge'):
                browser_probe(BOOK, out, 'A', 'B', confirm_rights=True, chromium=chromium)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK])
            self.assertFalse(out.exists())
            self.assertTrue(chromium.browser.closed)

    def test_cf_mitigated_challenge_header_always_stops(self):
        chromium = FakeChromium({
            BOOK: (CATALOG, 200, None, {"cf-mitigated": "challenge"})
        })
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with self.assertRaisesRegex(BrowserProbeError, 'cf-mitigated'):
                browser_probe(BOOK, out, 'A', 'B',
                              confirm_rights=True, chromium=chromium)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK])
            self.assertFalse(out.exists())

    def test_unrelated_challenge_script_strings_do_not_block_real_pages(self):
        script = ('<script>window.cf_chl_opt = "cf-challenge"; '
                  'var scriptPath = "challenge-platform";</script>')
        chromium = FakeChromium({
            BOOK: CATALOG + script,
            CH1: BODY1 + script,
            CH2: BODY2 + script,
        })
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = browser_probe(BOOK, out, 'Original story', 'Author',
                                   confirm_rights=True, chromium=chromium)
            self.assertEqual(result['chapter_count'], 2)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK, CH1, CH2])

    def test_challenge_only_visible_page_stops_without_header(self):
        chromium = FakeChromium({
            BOOK: ('<html><body><p>Verify you are human to continue</p></body></html>', 200, None)
        })
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with self.assertRaisesRegex(BrowserProbeError, 'human-verification challenge'):
                browser_probe(BOOK, out, 'A', 'B',
                              confirm_rights=True, chromium=chromium)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK])
            self.assertFalse(out.exists())

    def test_http_403_does_not_retry(self):
        chromium = FakeChromium({BOOK: ('<html>access denied</html>', 403, None)})
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(BrowserProbeError, 'HTTP 403'):
                browser_probe(BOOK, Path(tmp) / 'out', 'A', 'B',
                              confirm_rights=True, chromium=chromium)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK])

    def test_redirect_to_login_is_rejected(self):
        chromium = FakeChromium({BOOK: (CATALOG, 200, 'https://www.webnovel.com/login')})
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(BrowserProbeError, 'redirected'):
                browser_probe(BOOK, Path(tmp) / 'out', 'A', 'B',
                              confirm_rights=True, chromium=chromium)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK])

    def test_reader_locked_chapter_stops_and_discards_output(self):
        chromium = FakeChromium({
            BOOK: CATALOG, CH1: BODY1,
            CH2: '<html><div class="cha-content">Unlock this chapter to continue reading</div></html>',
        })
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with self.assertRaisesRegex(BrowserProbeError, 'Chapter 2: .*locked'):
                browser_probe(BOOK, out, 'A', 'B',
                              confirm_rights=True, chromium=chromium)
            self.assertFalse(out.exists())

    def test_optional_user_supplied_public_links(self):
        chromium = FakeChromium({BOOK: '<html>Book with hidden catalogue</html>', CH1: BODY1, CH2: BODY2})
        with TemporaryDirectory() as tmp:
            result = browser_probe(
                BOOK, Path(tmp) / 'out', 'A', 'B',
                confirm_rights=True, chapter_urls=[CH1, CH2], chromium=chromium)
            self.assertEqual(result['chapter_count'], 2)
            self.assertEqual(chromium.browser.context.page.visited, [BOOK, CH1, CH2])

    def test_catalogue_without_links_fails_closed(self):
        chromium = FakeChromium({BOOK: '<html>Book with hidden catalogue</html>'})
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(BrowserProbeError, 'Could not find'):
                browser_probe(BOOK, Path(tmp) / 'out', 'A', 'B',
                              confirm_rights=True, chromium=chromium)

    def test_public_chapter_urls_only(self):
        chromium = FakeChromium({})
        with self.assertRaises(ValueError):
            browser_probe(
                BOOK, 'out', 'A', 'B', confirm_rights=True,
                chapter_urls=['http://evil.com/one', CH2], chromium=chromium)

    def test_cli_requires_matching_chapter_urls(self):
        with self.assertRaises(SystemExit):
            main([
                BOOK, '--book-title', 'A', '--author', 'B',
                '--output-dir', 'out', '--confirm-rights',
                '--chapter-1-url', CH1,
            ])


if __name__ == '__main__':
    unittest.main()
