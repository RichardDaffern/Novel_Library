"""Offline-only tests for the bounded FreeWebNovel feasibility probe."""
import json
import unittest

from tools.freewebnovel_probe import (
    ProbeError, chapter_url, inspect_chapter, parse_catalogue, probe,
    validate_book_url,
)

BOOK = "https://freewebnovel.com/novel/the-first-order"
CH1 = BOOK + "/chapter-1"
CH2 = BOOK + "/chapter-2"
CH100 = BOOK + "/chapter-100"
CATALOG = f"""<html><head><title>Website</title></head><body>
<h1>The First Order</h1>
<a href="{CH100}">Chapter 100 - Latest release</a>
<section class="chapter-list">
<a href="/novel/the-first-order/chapter-1">Chapter 1 - Opening</a>
<a href="/novel/the-first-order/chapter-2">Chapter 2 - Second chapter</a>
<a href="/novel/the-first-order/chapter-3">Chapter 3</a>
</section></body></html>"""
BODY1 = """<html><h1>Read Online</h1><div class="txt">
<script>tracking()</script><div class="ads">BUY NOW</div>
<p>Chapter one introduces the main character at a quiet crossroads.
The villagers are gathering at the market. The evening air is cool and
the landscape around the town is filled with mountains and forests.</p>
<p>The next day is expected to bring new journeys and uncertain paths.
The travellers prepare carefully for their long voyage through the hills.</p>
</div><nav>Comment section</nav></html>"""
BODY2 = BODY1.replace("Chapter one", "Chapter two").replace("The villagers", "The visitors")


class FreeWebNovelTests(unittest.TestCase):
    def test_known_book_url(self):
        self.assertEqual(validate_book_url(BOOK), BOOK)
        self.assertEqual(validate_book_url(BOOK + "/"), BOOK)

    def test_refuse_unrelated_hosts_credentials_query_and_home(self):
        bad = (
            "https://freewebnovel.com/home",
            "https://freewebnovel.com/",
            BOOK + "?auth=secret",
            "http://freewebnovel.com/novel/the-first-order",
            "https://freewebnovel.com.evil.test/novel/the-first-order",
            "https://user:pass@freewebnovel.com/novel/the-first-order",
            "https://freewebnovel.com:8443/novel/the-first-order",
        )
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ProbeError):
                validate_book_url(url)

    def test_chapter_url_requires_same_book_and_https(self):
        self.assertEqual(chapter_url(CH2, BOOK), (CH2, 2))
        for url in (
            BOOK + "/chapter-0",
            BOOK + "/chapter-1?token=x",
            "https://freewebnovel.com/novel/another-book/chapter-1",
            "https://evil.test/novel/the-first-order/chapter-1",
        ):
            with self.subTest(url=url), self.assertRaises(ProbeError):
                chapter_url(url, BOOK)

    def test_catalogue_selects_first_two_not_latest(self):
        value = parse_catalogue(CATALOG, BOOK)
        self.assertEqual(value["title"], "The First Order")
        self.assertEqual([x["url"] for x in value["chapters"]], [CH1, CH2])

    def test_catalogue_missing_first_chapter_rejected(self):
        with self.assertRaisesRegex(ProbeError, "Chapters 1 and 2"):
            parse_catalogue('<html><h1>A novel</h1><a href="/novel/the-first-order/chapter-2">Chapter 2</a></html>', BOOK)

    def test_body_selector_removes_ads_and_returns_only_diagnostics(self):
        value = inspect_chapter(BODY1, position=1)
        self.assertEqual(value["position"], 1)
        self.assertGreater(value["characters"], 200)
        self.assertEqual(value["selector"], ".txt")
        self.assertNotIn("text", value)

    def test_unrecognized_or_short_body_rejected(self):
        with self.assertRaisesRegex(ProbeError, "no recognised"):
            inspect_chapter("<html><body>Read more in the app</body></html>", position=1)
        with self.assertRaisesRegex(ProbeError, "short"):
            inspect_chapter('<div class="txt">tiny</div>', position=1)

    def test_locked_and_challenge_pages_rejected(self):
        with self.assertRaisesRegex(ProbeError, "locked"):
            inspect_chapter('<div class="txt">Unlock this chapter to continue</div>', position=2)
        with self.assertRaisesRegex(ProbeError, "challenge"):
            inspect_chapter("<html><title>Just a moment...</title></html>", position=2)

    def test_three_page_ceiling_and_no_saved_content(self):
        requests = []
        pauses = []
        pages = {BOOK: CATALOG, CH1: BODY1, CH2: BODY2}
        def fetch(url):
            requests.append(url)
            return pages[url]
        result = probe(BOOK, confirm_rights=True, fetcher=fetch, sleeper=pauses.append)
        self.assertEqual(requests, [BOOK, CH1, CH2])
        self.assertEqual(pauses, [1, 1])
        self.assertEqual(result["title"], "The First Order")
        self.assertEqual([r["position"] for r in result["chapter_checks"]], [1, 2])
        self.assertTrue(result["retrieval_feasible_for_two_public_chapters"])
        self.assertFalse(result["download_supported"])
        self.assertNotIn("quiet crossroads", json.dumps(result))

    def test_catalogue_only_fetches_one_page(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return CATALOG
        result = probe(BOOK, catalog_only=True, fetcher=fetch)
        self.assertEqual(calls, [BOOK])
        self.assertNotIn("chapter_checks", result)

    def test_rights_flag_required_before_any_request(self):
        calls = []
        with self.assertRaisesRegex(ProbeError, "confirm-rights"):
            probe(BOOK, fetcher=lambda url: calls.append(url))
        self.assertEqual(calls, [])

    def test_error_on_second_chapter_does_not_report_success(self):
        requests = []
        def fetch(url):
            requests.append(url)
            return {BOOK: CATALOG, CH1: BODY1, CH2: '<div class="txt">Unlock this chapter</div>'}[url]
        with self.assertRaisesRegex(ProbeError, "locked"):
            probe(BOOK, confirm_rights=True, fetcher=fetch, sleeper=lambda x: None)
        self.assertEqual(requests, [BOOK, CH1, CH2])


if __name__ == "__main__":
    unittest.main()
