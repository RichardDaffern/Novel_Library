"""Offline tests for source-feasibility parsing and restored bulk menus."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.source_feasibility import (
    SourceProbeError, analyse_saved_pages, main, parse_book_info,
    parse_chapter_links, probe_saved_chapter, validate_book_url,
)

NF = "https://novelfire.net/book/martial-world"
LNP = "https://lightnovelpub.com/novel/reverend-insanity-05122222"

BOOK = """
<h1>Martial World</h1>
<p>Author: <a href="/author/cocooned-cow">Cocooned Cow</a></p>
<div class="summary"><div class="content">A mysterious cube changes the world.</div></div>
<p>2276 Chapters</p>
"""
INDEX = """
<a href="/book/martial-world/chapter-2">Chapter 1: Lin Ming</a>
<a href="/book/martial-world/chapter-1">Prologue</a>
<a href="/book/martial-world/chapter-1">duplicate</a>
<a href="/book/other/chapter-3">Wrong book</a>
<a href="https://example.org/book/martial-world/chapter-4">Wrong site</a>
"""
PROSE = " ".join(
    "These words are invented entirely for the offline feasibility regression test."
    for _ in range(30)
)
CHAPTER = f'<div id="chapter-content"><p>{PROSE}</p><p>{PROSE}</p><p>{PROSE}</p></div>'


class ExperimentalSourcesTests(unittest.TestCase):
    def test_supported_url_validation_and_rejection(self):
        self.assertEqual(validate_book_url(NF), ("NovelFire", NF))
        self.assertEqual(
            validate_book_url("https://www.lightnovelpub.com/novel/reverend-insanity-05122222/"),
            ("LightNovelPub", LNP)
        )
        for url in (
            "http://novelfire.net/book/martial-world",
            NF + "/chapter-1", NF + "?login=1",
            "https://novelfire.net.evil.com/book/martial-world",
            "https://lightnovelpub.org/novel/reverend-insanity",
            "https://lightnovelpub.com/",
            "https://user:pass@novelfire.net/book/martial-world"
        ):
            with self.subTest(url=url), self.assertRaises(SourceProbeError):
                validate_book_url(url)

    def test_novelfire_metadata_and_chapter_index(self):
        info = parse_book_info(BOOK, NF)
        self.assertEqual(info["title"], "Martial World")
        self.assertEqual(info["author"], "Cocooned Cow")
        self.assertEqual(info["chapter_count_reported"], 2276)
        self.assertTrue(info["synopsis_present"])
        self.assertEqual([x["position"] for x in parse_chapter_links(INDEX, NF)], [1, 2])

    def test_lightnovelpub_separate_book_domain(self):
        html = '<h1>Reverend Insanity</h1><div itemprop="author">Gu Zhen Ren</div>' \
               '<p>2334 Chapters</p><a href="/novel/reverend-insanity-05122222/chapter-1">1</a>'
        info = parse_book_info(html, LNP)
        self.assertEqual(info["website"], "LightNovelPub")
        self.assertEqual(info["chapter_count_reported"], 2334)
        self.assertEqual(len(parse_chapter_links(html, LNP)), 1)

    def test_at_most_two_verified_saved_chapters_never_export_prose(self):
        report = analyse_saved_pages(NF, BOOK, INDEX, [CHAPTER, CHAPTER], True)
        self.assertTrue(report["two_chapter_static_feasible"])
        self.assertFalse(report["download_supported"])
        self.assertEqual(len(report["chapter_checks"]), 2)
        self.assertEqual(len(report["chapter_checks"][0]["sha256"]), 64)
        self.assertNotIn(PROSE[:80], json.dumps(report))
        with self.assertRaisesRegex(SourceProbeError, "confirm-rights"):
            analyse_saved_pages(NF, BOOK, INDEX, [CHAPTER])
        with self.assertRaisesRegex(SourceProbeError, "At most two"):
            analyse_saved_pages(NF, BOOK, INDEX, [CHAPTER] * 3, True)

    def test_missing_text_paywall_and_short_text_rejected(self):
        for sample in (
            "<p>Only site navigation is present</p>",
            '<div id="chapter-content">A short footer</div>',
            '<div id="chapter-content">Purchase this chapter</div>'
        ):
            with self.subTest(sample=sample), self.assertRaises(SourceProbeError):
                probe_saved_chapter(sample)

    def test_wtrlab_modern_book_and_chapter_links_offline(self):
        url = "https://wtr-lab.com/en/novel/6965/myriad-paths"
        self.assertEqual(
            validate_book_url(url), ("WTRLab", url)
        )
        self.assertEqual(
            validate_book_url("https://www.wtr-lab.com/en/novel/6965/myriad-paths/"),
            ("WTRLab", url)
        )
        html = (
            '<h1>Myriad Paths</h1>'
            '<div itemprop="author">Original Author</div>'
            '<div class="desc-text">A cultivation adventure.</div>'
            '<p>620 Chapters</p>'
        )
        info = parse_book_info(html, url)
        self.assertEqual(info["website"], "WTRLab")
        self.assertEqual(info["chapter_count_reported"], 620)
        toc = (
            '<a href="/en/novel/6965/myriad-paths/chapter-2">Chapter Two</a>'
            '<a href="/en/novel/6965/myriad-paths/chapter-1">Chapter One</a>'
            '<a href="/en/novel/6966/other/chapter-1">Other Book</a>'
            '<a href="/en/novel/6965/myriad-paths/chapter-3?unlock=1">Locked</a>'
        )
        chapters = parse_chapter_links(toc, url)
        self.assertEqual([c["position"] for c in chapters], [1, 2])
        with self.assertRaises(SourceProbeError):
            validate_book_url("https://wtr-lab.com/en/novel/6965/myriad-paths/chapter-1")
        for locked in ("Unlock Chapter", "This chapter requires tickets"):
            with self.subTest(locked=locked), self.assertRaises(SourceProbeError):
                probe_saved_chapter(
                    '<div id="chapter-content"><p>' + locked + '</p></div>'
                )

    def test_royalroad_chapter_ids_are_not_position_numbers(self):
        url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
        label, canonical = validate_book_url(url)
        self.assertEqual(label, "RoyalRoad")
        self.assertEqual(canonical, "https://royalroad.com/fiction/21220/mother-of-learning")
        toc = (
            '<a href="/fiction/21220/mother-of-learning/chapter/301778/1-good-morning-brother">'
            '1. Good Morning, Brother</a>'
            '<a href="/fiction/21220/mother-of-learning/chapter/299000/prologue">Prologue</a>'
            '<a href="/fiction/21220/mother-of-learning/chapter/301778/1-good-morning-brother">'
            'Duplicate</a>'
            '<a href="/fiction/99999/wrong/chapter/999999/other">Other book</a>'
        )
        chapters = parse_chapter_links(toc, url)
        self.assertEqual(len(chapters), 2)
        self.assertEqual([c["position"] for c in chapters], [1, 2])
        self.assertEqual([c["chapter_id"] for c in chapters], ["301778", "299000"])
        self.assertEqual(chapters[0]["title"], "1. Good Morning, Brother")
        with self.assertRaises(SourceProbeError):
            validate_book_url(url + "/chapter/301778/1-good-morning-brother")

    def test_local_cli_no_network_and_no_chapter_text_in_report(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / name for name in ("book.html", "index.html", "one.html", "two.html")]
            for path, content in zip(paths, (BOOK, INDEX, CHAPTER, CHAPTER)):
                path.write_text(content, encoding="utf-8")
            report = root / "report.json"
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = main([NF, "--book-html", str(paths[0]), "--index-html", str(paths[1]),
                           "--chapter-html", str(paths[2]), "--chapter-html", str(paths[3]),
                           "--confirm-rights", "--report", str(report)])
            self.assertEqual(rc, 0, stderr.getvalue())
            saved = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(saved["two_chapter_static_feasible"])
            self.assertNotIn(PROSE[:80], report.read_text(encoding="utf-8"))

    def test_single_bulk_action_remains_and_extra_menus_are_absent(self):
        common = Path(".github/workflows/library-bulk-download.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: Library - Bulk Download", common)
        self.assertIn("  workflow_dispatch:", common)
        self.assertNotIn("  workflow_call:", common)
        self.assertIn("          - All", common)
        self.assertIn("          - NovelFull", common)
        self.assertIn("          - FreeWebNovel", common)
        self.assertIn("    uses: ./.github/workflows/download-novel.yml", common)
        self.assertIn("    uses: ./.github/workflows/freewebnovel-download.yml", common)
        self.assertIn("max-parallel: 3", common)
        self.assertIn("max-parallel: 2", common)
        for redundant in (
            "novelfull-bulk-download.yml", "freewebnovel-bulk-download.yml"
        ):
            self.assertFalse((Path(".github/workflows") / redundant).exists())


if __name__ == "__main__":
    unittest.main()
