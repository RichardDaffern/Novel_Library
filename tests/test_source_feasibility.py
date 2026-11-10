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

    def test_restored_site_bulk_menus_reuse_common_implementation(self):
        common = Path(".github/workflows/library-bulk-download.yml").read_text(encoding="utf-8")
        self.assertIn("  workflow_call:", common)
        self.assertIn("  workflow_dispatch:", common)
        self.assertIn("    uses: ./.github/workflows/download-novel.yml", common)
        self.assertIn("    uses: ./.github/workflows/freewebnovel-download.yml", common)
        for website, filename in (("NovelFull", "novelfull-bulk-download.yml"),
                                  ("FreeWebNovel", "freewebnovel-bulk-download.yml")):
            wrapper = Path(".github/workflows", filename).read_text(encoding="utf-8")
            self.assertIn(f"name: {website} - Bulk Download", wrapper)
            self.assertIn("  workflow_dispatch:", wrapper)
            self.assertIn("uses: ./.github/workflows/library-bulk-download.yml", wrapper)
            self.assertIn(f"website: {website}", wrapper)
            for name in ("novel_names", "novel_urls", "chapter_range", "force"):
                self.assertIn("      " + name + ": ${{ inputs." + name + " }}", wrapper)
            self.assertNotIn("python -u -m tools.chunked_download", wrapper)
            self.assertNotIn("python -u -m tools.freewebnovel_chunks", wrapper)


if __name__ == "__main__":
    unittest.main()
