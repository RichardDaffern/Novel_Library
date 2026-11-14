"""Offline-only compatibility tests for FanFicFare's Scribble Hub adapter.

Synthetic site HTML only. No credentials, networking, chapters from real books,
or modifications to Novel_Library's supported website list.
"""
import re
import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup
from fanficfare.adapters.adapter_scribblehubcom import ScribbleHubComAdapter

from novel_downloader import validate_url
from tools.library_bulk import _validated_url


SERIES = "https://www.scribblehub.com/series/2677327/blueflame-the-starless-king/"
CHAPTER = "https://www.scribblehub.com/read/2677327-blueflame-the-starless-king/chapter/7654321/"
SERIES_HTML = """
<html><head><link rel="canonical" href="https://www.scribblehub.com/series/2677327/blueflame-the-starless-king/"></head>
<body><div class="fic_title">Synthetic Story</div>
<span class="auth_name_fic">Example Writer</span>
<div class="author"><div property="author"><span property="name"><a href="https://www.scribblehub.com/profile/123/">Example Writer</a></span></div></div>
<div class="wi_fic_desc">Synthetic description written for a unit test</div>
<a class="fic_genre">Fantasy</a>
<span title="Last updated: Nov 12, 2026 08:52 AM">Nov 12, 2026</span>
<span class="fic_date_pub">Nov 12, 2026</span>
</body></html>
"""
CHAPTER_INDEX = """
<a class="toc_a" href="https://www.scribblehub.com/read/2677327-example/chapter/111/">Synthetic Chapter One</a>
<a class="toc_a" href="https://www.scribblehub.com/read/2677327-example/chapter/222/">Synthetic Chapter Two</a>
"""
CHAPTER_HTML = """
<div id="chp_raw"><p>Original made-up text solely for a synthetic test.</p>
<div class="wi_authornotes"><div class="wi_authornotes_body">Fictional note</div></div></div>
"""


class FakeStory:
    def __init__(self):
        self.metadata = {}

    def setMetadata(self, name, value):
        self.metadata[name] = value

    def getMetadata(self, name):
        return self.metadata.get(name)

    def addToList(self, name, value):
        self.metadata.setdefault(name, []).append(value)


class TestScribbleHubOffline(unittest.TestCase):
    def fake_adapter(self):
        adapter = ScribbleHubComAdapter.__new__(ScribbleHubComAdapter)
        adapter.url = SERIES
        adapter.urltitle = "blueflame-the-starless-king"
        adapter.dateformat = "%b %d, %Y"
        adapter.story = FakeStory()
        adapter.story.setMetadata("storyId", "2677327")
        adapter.make_soup = lambda html: BeautifulSoup(html, "html.parser")
        adapter.set_contents_cookie = lambda: None
        adapter.get_request = lambda url: "<table class='table_pro_overview'><tr><th>Word Count</th><td>1234</td></tr></table>" if url.endswith("/stats/") else SERIES_HTML
        adapter.post_request = Mock(return_value=CHAPTER_INDEX)
        adapter.set_story_idurl = lambda url: None
        adapter.add_chapter = Mock()
        adapter.setDescription = Mock()
        adapter.setCoverImage = Mock()
        adapter.getConfigList = lambda name: []
        adapter.utf8FromSoup = lambda url, div: div.get_text(" ", strip=True)
        return adapter

    def test_fanficfare_recognises_series_and_read_url(self):
        pattern = ScribbleHubComAdapter._get_site_url_pattern()
        self.assertEqual(re.match(pattern, SERIES).group("id"), "2677327")
        self.assertEqual(re.match(pattern, CHAPTER).group("id"), "2677327")
        self.assertEqual(validate_url(SERIES), SERIES)

    def test_bulk_planner_rejects_unregistered_scribble_hub_work(self):
        # The adapter can parse public site HTML, but the bulk planner
        # permits only verified same-author cross-posts, not this series.
        with self.assertRaisesRegex(ValueError, "No author-verified"):
            _validated_url(SERIES)

    def test_synthetic_series_and_ajax_index_are_parsed_offline(self):
        adapter = self.fake_adapter()
        adapter.extractChapterUrlsAndMetadata(get_cover=False)
        self.assertEqual(adapter.story.metadata["title"], "Synthetic Story")
        self.assertEqual(adapter.story.metadata["author"], "Example Writer")
        self.assertEqual(adapter.story.metadata["genre"], ["Fantasy"])
        self.assertEqual(adapter.add_chapter.call_count, 2)
        adapter.post_request.assert_called_once()
        args, kwargs = adapter.post_request.call_args
        self.assertTrue(args[0].endswith("/wp-admin/admin-ajax.php"))
        self.assertEqual(args[1]["mypostid"], "2677327")
        self.assertEqual(args[1]["pagenum"], -1)

    def test_synthetic_chapter_text_selector_is_understood(self):
        adapter = self.fake_adapter()
        adapter.get_request = lambda url: CHAPTER_HTML
        body = adapter.getChapterText(CHAPTER)
        self.assertIn("Original made-up text", body)

    def test_two_synthetic_chapters_export_to_epub_and_utf8_manifests(self):
        import json
        from hashlib import sha256
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from novel_downloader import epub_chapters, export_epub
        from tools.chunked_download import _epub

        with TemporaryDirectory() as root:
            base = Path(root)
            book_dir = base / "source"
            book_dir.mkdir()
            rows = []
            for i in (1, 2):
                filename = f"chapter_{i:05d}.txt"
                content = f"Chapter {i}\n\nInvented example chapter {i} with original synthetic text.\n"
                (book_dir / filename).write_text(content, encoding="utf-8")
                rows.append({
                    "position": i, "chapter_number": i,
                    "title": f"Chapter {i}", "file": filename,
                    "sha256": sha256(content.encode("utf-8")).hexdigest(),
                    "word_count": len(content.split()),
                })
            _epub(book_dir, rows, "Synthetic Scribble Hub Example",
                  "Example Writer", "en", SERIES,
                  description="Synthetic description", genres=["Fantasy"])
            epmeta, epchapters = epub_chapters(book_dir / "source.epub")
            self.assertEqual(len(epchapters), 2)
            self.assertEqual(epmeta["description"], "Synthetic description")

            exported = base / "exported"
            result = export_epub(book_dir / "source.epub", exported, SERIES)
            manifest = json.loads((exported / "chapters.json").read_text(encoding="utf-8"))
            self.assertEqual(result["chapter_count"], 2)
            self.assertEqual([item["position"] for item in manifest], [1, 2])
            meta = json.loads((exported / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["source_url"], SERIES)
            self.assertEqual(meta["description"], "Synthetic description")
            for chapter in manifest:
                path = exported / chapter["file"]
                self.assertTrue(path.is_file())
                self.assertEqual(
                    sha256(path.read_bytes()).hexdigest(), chapter["sha256"]
                )

    def test_access_denied_html_never_looks_like_a_valid_chapter(self):
        adapter = self.fake_adapter()
        adapter.get_request = lambda url: "<html><title>Access denied</title><body>403 Forbidden</body></html>"
        # Current upstream adapter raises before its explicit Missing Element check.
        # The exception is a known diagnostic weakness, not a novel download.
        with self.assertRaises(Exception):
            adapter.getChapterText(CHAPTER)


if __name__ == "__main__":
    unittest.main()
