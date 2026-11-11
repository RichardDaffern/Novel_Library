import json
import shutil
from html import escape
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from novel_downloader import export_epub, epub_chapters, main, slugify, validate_url, run_fanficfare, parse_chapter_range
from fff_progress_runner import _checkpoint_chapter, progress_reporter


class NovelDownloaderTests(unittest.TestCase):
    def make_epub(self, root: Path, chapter_titles=None, description=""):
        if chapter_titles is None:
            chapter_titles = ["Prologue", "Chapter 1: Return", "Chapter 2: A Journey"]
        epub = root / "fixture.epub"
        items = [f'<item id="ch{i}" href="chapter{i}.xhtml" media-type="application/xhtml+xml" />'
                 for i in range(len(chapter_titles))]
        spine = [f'<itemref idref="ch{i}" />' for i in range(len(chapter_titles))]
        package = (f'<package xmlns="http://www.idpf.org/2007/opf">'
                   f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<dc:title>Example Novel</dc:title><dc:creator>Example Author</dc:creator>'
                   f'<dc:language>en</dc:language>'
                   + (f'<dc:description>{escape(description)}</dc:description>' if description else '') +
                   '</metadata>'
                   f'<manifest><item id="cover" href="title.xhtml" media-type="application/xhtml+xml" />{"".join(items)}</manifest>'
                   f'<spine><itemref idref="cover" />{"".join(spine)}</spine></package>')
        with zipfile.ZipFile(epub, "w") as archive:
            archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/content.opf" /></rootfiles></container>')
            archive.writestr("OEBPS/content.opf", package)
            archive.writestr("OEBPS/title.xhtml", '<html><body><p>Not a chapter</p></body></html>')
            for i, title in enumerate(chapter_titles):
                archive.writestr(f"OEBPS/chapter{i}.xhtml", f'<html><head><title>{title}</title></head><body class="fff_chapter"><h3 class="fff_chapter_title">{title}</h3><p>Paragraph {i}.</p><p>More text here.</p></body></html>')
        return epub

    def test_export_orders_numbers_and_ignores_title_page(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self.make_epub(root)
            metadata = export_epub(archive, root / "out", "https://example.com/novel")
            self.assertEqual(metadata["chapter_count"], 3)
            self.assertEqual(metadata["synopsis_pipeline_version"], 2)
            names = [row["file"] for row in json.loads((root / "out/chapters.json").read_text())]
            self.assertEqual(names, ["chapter_0000_prologue.txt", "chapter_0001.txt", "chapter_0002.txt"])
            self.assertIn("Paragraph 1.\n\nMore text here.", (root / "out/chapter_0001.txt").read_text())
            self.assertNotIn("Not a chapter", (root / "out/chapter_0001.txt").read_text())

    def test_source_epub_synopsis_is_preserved_in_exported_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            epub = self.make_epub(
                root, description="<p>A clever villain with a choice system.</p>"
                                  "<p>He challenges the original hero &amp; changes his fate.</p>"
            )
            metadata = export_epub(epub, root / "out", "https://example.org/book")
            expected = ("A clever villain with a choice system.\n"
                        "He challenges the original hero & changes his fate.")
            self.assertEqual(metadata["description"], expected)
            self.assertEqual(metadata["synopsis"], expected)
            saved = json.loads((root / "out" / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["description"], expected)
            self.assertEqual(saved["chapter_count"], 3)

    def test_epub_without_description_keeps_metadata_backwards_compatible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metadata = export_epub(self.make_epub(root), root / "out")
            self.assertNotIn("description", metadata)
            self.assertNotIn("synopsis", metadata)

    def test_duplicate_titles_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self.make_epub(root, ["Chapter 1: Hello", "Chapter 1: Hello"])
            export_epub(archive, root / "out")
            self.assertTrue((root / "out/chapter_0001.txt").is_file())
            self.assertTrue((root / "out/chapter_0001_part02.txt").is_file())

    def test_existing_file_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            epub = self.make_epub(root)
            rc = main(["--import-epub", str(epub), "--output-dir", str(root / "downloads")])
            self.assertEqual(rc, 0)
            self.assertTrue((root / "downloads/example-novel/source.epub").is_file())


    def test_distinct_sources_with_identical_path_stems_get_distinct_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.make_epub(root)
            def download(url, directory, *args):
                shutil.copyfile(fixture, directory / "source.epub")
            with patch("novel_downloader.run_fanficfare", side_effect=download):
                first = main(["https://example.org/story/identical", "--confirm-rights", "--output-dir", str(root / "out")])
                second = main(["https://example.com/books/identical", "--confirm-rights", "--output-dir", str(root / "out")])
            self.assertEqual((first, second), (0, 0))
            folders = list((root / "out").iterdir())
            self.assertEqual(len(folders), 2)
            self.assertEqual({json.loads((p / "metadata.json").read_text())["source_url"] for p in folders},
                             {"https://example.org/story/identical", "https://example.com/books/identical"})

    def test_explicit_slug_cannot_reuse_a_different_url(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.make_epub(root)
            def download(url, directory, *args):
                shutil.copyfile(fixture, directory / "source.epub")
            with patch("novel_downloader.run_fanficfare", side_effect=download):
                self.assertEqual(main(["https://example.org/a", "--confirm-rights", "--slug", "shared",
                                       "--output-dir", str(root / "out")]), 0)
                self.assertEqual(main(["https://example.com/b", "--confirm-rights", "--slug", "shared",
                                       "--output-dir", str(root / "out"), "--overwrite"]), 1)
            saved = json.loads((root / "out/shared/metadata.json").read_text())
            self.assertEqual(saved["source_url"], "https://example.org/a")

    def test_same_title_import_refuses_different_epub_unless_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = root / "a", root / "b"
            a.mkdir()
            b.mkdir()
            first = self.make_epub(a)
            second = self.make_epub(b, ["Different Chapter", "Chapter 1: New"])
            cmd = ["--import-epub", str(first), "--output-dir", str(root / "out")]
            self.assertEqual(main(cmd), 0)
            target = root / "out/example-novel/source.epub"
            original = target.read_bytes()
            self.assertEqual(main(["--import-epub", str(second), "--output-dir", str(root / "out")]), 1)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(main(["--import-epub", str(second), "--output-dir", str(root / "out"),
                                   "--overwrite"]), 0)
            self.assertEqual(target.read_bytes(), second.read_bytes())

    def test_failed_stage_write_preserves_old_chapters_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = root / "a", root / "b"
            a.mkdir()
            b.mkdir()
            first = self.make_epub(a)
            second = self.make_epub(b, ["Only one different chapter"])
            out = root / "out"
            export_epub(first, out)
            original = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
            write = Path.write_text
            def fail_manifest(path, content, *args, **kwargs):
                if path.name == "chapters.json":
                    raise OSError("injected failure before publication")
                return write(path, content, *args, **kwargs)
            with patch.object(Path, "write_text", fail_manifest):
                with self.assertRaises(OSError):
                    export_epub(second, out)
            self.assertEqual(original, {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()})

    def test_failed_redownload_preserves_published_book(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.make_epub(root)
            def download(url, directory, *args):
                shutil.copyfile(fixture, directory / "source.epub")
            args = ["https://example.org/same", "--confirm-rights", "--output-dir", str(root / "out")]
            with patch("novel_downloader.run_fanficfare", side_effect=download):
                self.assertEqual(main(args), 0)
            book = next((root / "out").iterdir())
            original = {p.name: p.read_bytes() for p in book.iterdir() if p.is_file()}
            with patch("novel_downloader.run_fanficfare", side_effect=OSError("simulated download failure")):
                self.assertEqual(main(args + ["--overwrite"]), 1)
            self.assertEqual(original, {p.name: p.read_bytes() for p in book.iterdir() if p.is_file()})

    def test_recovers_previous_export_backup_when_directory_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.make_epub(root)
            out = root / "out"
            export_epub(fixture, out)
            backup = root / ".out.backup-simulated-interruption"
            out.replace(backup)
            self.assertFalse(out.exists())
            export_epub(fixture, out)
            self.assertTrue((out / "metadata.json").is_file())
            self.assertFalse(backup.exists())

    def test_cleanup_preserves_untracked_chapter_named_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = root / "a", root / "b"
            a.mkdir()
            b.mkdir()
            old = self.make_epub(a)
            new = self.make_epub(b, ["Chapter 1: A Shorter Work"])
            out = root / "out"
            export_epub(old, out)
            unrelated = out / "chapter_9999.txt"
            unrelated.write_text("Not managed by Novel Library")
            export_epub(new, out)
            self.assertEqual(unrelated.read_text(), "Not managed by Novel Library")
            rows = json.loads((out / "chapters.json").read_text())
            self.assertEqual(len(rows), 1)
            self.assertFalse((out / "chapter_0002.txt").exists())

    def test_expected_chapters_rejects_short_successful_epub(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.make_epub(root)
            def download(url, directory, *args):
                shutil.copyfile(fixture, directory / "source.epub")
            with patch("novel_downloader.run_fanficfare", side_effect=download):
                rc = main(["https://example.org/book", "--confirm-rights",
                           "--expected-chapters", "8", "--output-dir", str(root / "out")])
            self.assertEqual(rc, 1)

    def test_url_rejects_literal_ip_and_local_network_names(self):
        for url in ("https://127.0.0.2/book", "https://169.254.169.254/book",
                    "https://10.0.0.5/book", "https://[::1]/book",
                    "https://[fc00::1]/book", "https://private.internal/book",
                    "https://server.local/book", "https://localhost.evil.internal/book",
                    "https://example.com:8443/book"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_public_domain_style_epub_without_fanficfare_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            epub = root / "sample.epub"
            with zipfile.ZipFile(epub, "w") as z:
                z.writestr("META-INF/container.xml", '<container><rootfile full-path="content.opf" /></container>')
                z.writestr("content.opf", '<package><metadata><title>Short public domain book</title></metadata><manifest><item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"/><item id="story" href="story.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="cover"/><itemref idref="nav"/><itemref idref="story"/></spine></package>')
                z.writestr("cover.xhtml", '<html><head><title>Cover</title></head><body><img src="cover.jpg"/></body></html>')
                z.writestr("nav.xhtml", '<html><body><p>Contents</p></body></html>')
                z.writestr("story.xhtml", '<html><body><h1>A short story</h1><p>' + ('This is public-domain test text. ' * 30) + '</p></body></html>')
            meta = export_epub(epub, root / "out")
            self.assertEqual(meta["chapter_count"], 1)
            self.assertTrue((root / "out/chapter_0001.txt").exists())

    def test_empty_epub_fails_loudly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            epub = self.make_epub(root, [])
            with self.assertRaises(ValueError):
                epub_chapters(epub)

    def test_url_rejection(self):
        for url in ["http://example.org/book", "https://foo:bar@example.org/book", "https://localhost/book"]:
            with self.assertRaises(ValueError):
                validate_url(url)
        self.assertEqual(slugify("A Story: One!"), "a-story-one")

    def test_discovery_command_does_not_download(self):
        with patch("novel_downloader.shutil.which", return_value="fanficfare"), patch("novel_downloader.subprocess.run") as runner:
            rc = main(["https://example.com/book", "--confirm-rights", "--list-only"])
            self.assertEqual(rc, 0)
            args = runner.call_args.args[0]
            self.assertIn("--no-output", args)
            self.assertNotIn("--progressbar", args)

    def test_chapter_range_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("novel_downloader.shutil.which", return_value="fanficfare"), patch("novel_downloader.subprocess.run") as runner:
                run_fanficfare("https://example.com/novel", Path(temp), False, 10, 20)
                args = runner.call_args.args[0]
                self.assertEqual(args[args.index("--begin")+1], "10")
                self.assertEqual(args[args.index("--end")+1], "20")
                self.assertIn("fff_progress_runner.py", str(args[1]))
                self.assertNotIn("--progressbar", args)

    def test_synthetic_end_to_end_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("novel_downloader.shutil.which", return_value="fanficfare"), patch("novel_downloader.subprocess.run") as runner:
                rc = main(["--self-test", "--output-dir", temp])
                self.assertEqual(rc, 1)  # Mocked downloader does not write the EPUB
                args = runner.call_args.args[0]
                self.assertIn("http://test1.com?sid=123", args)
                self.assertIn("fff_progress_runner.py", str(args[1]))
                self.assertNotIn("--progressbar", args)



class ProgressReporterTests(unittest.TestCase):
    def test_full_book_percentages(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        writer = SimpleNamespace(adapter=SimpleNamespace(chapterInfos=[{}] * 4, chapterFirst=None, chapterLast=None))
        out = StringIO()
        with redirect_stdout(out):
            cb = progress_reporter(writer)
            for _ in range(4):
                cb(0.25, "url")
        self.assertIn("Chapters processed: 1/4 (25.0%)", out.getvalue())
        self.assertIn("Chapters processed: 4/4 (100.0%)", out.getvalue())

    def test_selected_chapter_range_percentage(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        writer = SimpleNamespace(adapter=SimpleNamespace(chapterInfos=[{}] * 300, chapterFirst=100, chapterLast=119))
        out = StringIO()
        with redirect_stdout(out):
            cb = progress_reporter(writer)
            for _ in range(20):
                cb(0.1, "url")
        self.assertIn("Chapter range: 20 selected of 300 chapters", out.getvalue())
        self.assertIn("Chapters processed: 20/20 (100.0%)", out.getvalue())



class ChapterRangeTests(unittest.TestCase):
    def test_range_is_inclusive(self):
        self.assertEqual(parse_chapter_range("3-5"), (3, 5))
        self.assertEqual(parse_chapter_range("5-5"), (5, 5))
        self.assertEqual(parse_chapter_range(" 12 - 25 "), (12, 25))

    def test_invalid_ranges_rejected(self):
        for raw in ("1", "zero-5", "0-1", "6-4", "-5", "2-", "1:5"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_chapter_range(raw)

    def test_export_preserves_index_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = NovelDownloaderTests().make_epub(root, ["Chapter 2", "Chapter 3", "Chapter 4"])
            exported = export_epub(epub, root / "out", first_position=3)
            rows = json.loads((root / "out/chapters.json").read_text())
            self.assertEqual(exported["chapter_count"], 3)
            self.assertEqual([r["position"] for r in rows], [3, 4, 5])

    def test_range_has_unique_folder_and_fanficfare_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("novel_downloader.shutil.which", return_value="fanficfare"), patch("novel_downloader.subprocess.run") as runner:
                result = main(["--self-test", "--chapter-range", "3-5", "--output-dir", tmp])
                self.assertEqual(result, 1) # fake process does not create EPUB
                args = runner.call_args.args[0]
                self.assertEqual(args[args.index("--begin")+1], "3")
                self.assertEqual(args[args.index("--end")+1], "5")
                self.assertIn("fanficfare-smoke-test-chapters-0003-0005", str(runner.call_args.kwargs["cwd"]))


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_is_written_before_epub(self):
        import os
        from types import SimpleNamespace
        from io import StringIO
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                adapter = SimpleNamespace(chapterInfos=[{"title": "Chapter 1"}],
                                          chapterFirst=None, chapterLast=None,
                                          getChapterTextNum=lambda url, i: "<div><p>First paragraph.</p><p>Second paragraph.</p></div>")
                with redirect_stdout(StringIO()) as output:
                    cb = progress_reporter(SimpleNamespace(adapter=adapter))
                    adapter.getChapterTextNum("https://example.org/ch1", 0)
                    cb(1, "https://example.org/ch1")
                checkpoint = Path(tmp) / "chapters_in_progress/chapter_00001.txt"
                self.assertTrue(checkpoint.is_file())
                self.assertIn("Second paragraph", checkpoint.read_text(encoding="utf-8"))
                self.assertIn("100.0%", output.getvalue())
                self.assertFalse((Path(tmp) / "source.epub").exists())
            finally:
                os.chdir(previous)

    def test_blank_chapter_is_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                _checkpoint_chapter(Path(tmp), 0, "Empty", "<html><body></body></html>")


if __name__ == "__main__":
    unittest.main()
