"""Synthetic tests for cover extraction, safe downloads, and EPUB preservation."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from PIL import Image

from novel_downloader import epub_chapters, export_epub
from tools.chunked_download import _epub, assemble, chapter_plan, identity
from tools.download_covers import (
    cover_basename, download_covers, read_markdown_novels, select_novels,
)
from tools.novel_covers import (
    CoverError, _image_candidates, download_site_cover, extract_epub_cover,
    validate_image, validate_public_url,
)

NOVELFULL = "https://novelfull.com/martial-world.html"
FREEWEB = "https://freewebnovel.com/novel/the-first-order"


def image_bytes(mode="JPEG"):
    out = BytesIO()
    Image.new("RGB", (100, 150), (80, 110, 180)).save(out, format=mode)
    return out.getvalue()


def piece(root, url, key, first, last, with_cover=False):
    folder = root / f"chapter-batch-{key}-{first:05d}-{last:05d}"
    book = folder / "book"
    book.mkdir(parents=True)
    rows = []
    for n in range(first, last + 1):
        filename = f"chapter_{n:05d}.txt"
        text = f"Chapter {n}\n\nA completely original test chapter with enough text for validation.\n"
        (book / filename).write_text(text, encoding="utf-8")
        rows.append({
            "position": n, "chapter_number": n, "title": f"Chapter {n}",
            "file": filename, "word_count": len(text.split()),
            "sha256": sha256(text.encode("utf-8")).hexdigest(),
        })
    meta = {
        "source_url": url, "chapter_count": len(rows),
        "title": "A Synthetic Novel", "author": "Test Author",
        "language": "en", "synopsis_pipeline_version": 2,
        "cover_pipeline_version": 1,
    }
    if with_cover:
        (book / "cover.jpg").write_bytes(image_bytes())
        meta["cover_image"] = "cover.jpg"
    (book / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (book / "chapters.json").write_text(json.dumps(rows), encoding="utf-8")
    _epub(book, rows, meta["title"], meta["author"], "en", url,
          cover_path=(book / "cover.jpg") if with_cover else None)
    (folder / "part.json").write_text(json.dumps({
        "version": 1, "url": url, "key": key,
        "start": first, "end": last,
    }), encoding="utf-8")
    return folder


class CoverPipelineTests(unittest.TestCase):
    def test_validate_jpeg_png_and_reject_html_or_tiny(self):
        self.assertEqual(validate_image(image_bytes())[1], ".jpg")
        self.assertEqual(validate_image(image_bytes("PNG"))[1], ".png")
        with self.assertRaises(CoverError):
            validate_image(b"<html>Not an image</html>")
        small = BytesIO()
        Image.new("RGB", (1, 2)).save(small, format="PNG")
        with self.assertRaises(CoverError):
            validate_image(small.getvalue())

    def test_dont_download_private_or_insecure_image_urls(self):
        for url in (
            "http://example.org/cover.jpg",
            "https://127.0.0.1/private.jpg",
            "https://localhost/cover.jpg",
            "https://user:password@example.org/photo.jpg",
            "https://10.1.1.1/image.png",
            "https://example.local/cover.jpg",
        ):
            with self.subTest(url=url), self.assertRaises(CoverError):
                validate_public_url(url)

    def test_novelfull_and_freeweb_catalogue_cover_candidates(self):
        html = (
            '<h1>Martial World</h1><div class="book-img">'
            '<img data-src="/uploads/martial-world-cover.jpg" src="placeholder.gif"></div>'
        )
        self.assertEqual(
            _image_candidates(html, NOVELFULL),
            ["https://novelfull.com/uploads/martial-world-cover.jpg"],
        )
        html2 = (
            '<h1>The First Order</h1>'
            '<meta property="og:image" content="https://images.example.com/book.jpg">'
        )
        self.assertEqual(
            _image_candidates(html2, FREEWEB),
            ["https://images.example.com/book.jpg"],
        )

    def test_public_cover_download_only_fetches_book_page_and_image(self):
        requests = []
        html = '<div class="book-img"><img src="/covers/martial-world.png"/></div>'
        def page_fetch(url):
            requests.append(("page", url))
            return html
        def fetch(url, referer):
            requests.append(("image", url, referer))
            return image_bytes("PNG")
        cover, ext, url = download_site_cover(
            NOVELFULL, html_fetcher=page_fetch, image_fetcher=fetch,
        )
        self.assertEqual(ext, ".png")
        self.assertEqual(cover, image_bytes("PNG"))
        self.assertEqual(requests, [
            ("page", NOVELFULL),
            ("image", "https://novelfull.com/covers/martial-world.png", NOVELFULL),
        ])

    def test_epub_export_extracts_source_cover_without_changing_chapters(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "original"
            original.mkdir()
            (original / "chapter_00001.txt").write_text(
                "Chapter 1\n\nFirst made-up chapter for testing.\n",
                encoding="utf-8",
            )
            rows = [{"title": "Chapter 1", "file": "chapter_00001.txt"}]
            (original / "cover.png").write_bytes(image_bytes("PNG"))
            _epub(original, rows, "Synthetic Novel", "Test Author", "en", NOVELFULL,
                  description="A harmless synthetic test novel.",
                  cover_path=original / "cover.png")
            cover = extract_epub_cover(original / "source.epub")
            self.assertIsNotNone(cover)
            self.assertEqual(cover[0], image_bytes("PNG"))
            metadata = export_epub(original / "source.epub", root / "export", NOVELFULL)
            self.assertEqual(metadata["cover_image"], "cover.png")
            self.assertEqual(
                (root / "export" / "cover.png").read_bytes(), image_bytes("PNG")
            )
            # export_epub exports chapters/metadata; the original EPUB stays at its source.
            self.assertEqual(len(epub_chapters(original / "source.epub")[1]), 1)

    def test_final_assembly_preserves_cover_after_two_ranges(self):
        plan = chapter_plan(NOVELFULL, 4, "1-4", chunk_size=2)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunks = root / "chunks"
            piece(chunks, NOVELFULL, identity(NOVELFULL), 1, 2, with_cover=True)
            piece(chunks, NOVELFULL, identity(NOVELFULL), 3, 4)
            book = assemble(plan, chunks, root / "assembled")
            data = json.loads((book / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(data["cover_image"], "cover.jpg")
            self.assertEqual((book / "cover.jpg").read_bytes(), image_bytes())
            with ZipFile(book / "source.epub") as archive:
                opf = archive.read("OEBPS/content.opf").decode("utf-8")
                self.assertIn('name="cover"', opf)
                self.assertIn("cover-image", opf)
                self.assertIsNone(archive.testzip())
            cover = extract_epub_cover(book / "source.epub")
            self.assertIsNotNone(cover)
            self.assertEqual(cover[0], image_bytes())
            self.assertEqual(len(epub_chapters(book / "source.epub")[1]), 4)

    def test_no_cover_is_allowed_and_not_invented(self):
        plan = chapter_plan(NOVELFULL, 2, "1-2", chunk_size=2)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            piece(root / "chunks", NOVELFULL, identity(NOVELFULL), 1, 2)
            book = assemble(plan, root / "chunks", root / "output")
            self.assertNotIn("cover_image", json.loads((book / "metadata.json").read_text()))
            self.assertIsNone(extract_epub_cover(book / "source.epub"))


class CoverOnlyDownloadTests(unittest.TestCase):
    def test_markdown_rows_deduplicated_and_grouped(self):
        sample = (
            "# Downloaded novels\n"
            "## NovelFull (2 novels)\n"
            "| Novel | Range | Chapters | Artifact | Expiry (UTC) |\n"
            "|---|---|---:|---|---|\n"
            f"| [Martial World]({NOVELFULL}) | all | 2255 | [Available](https://github.com/run) | tomorrow |\n"
            f"| [Martial World]({NOVELFULL}) | 1-2 | 2 | [Available](https://github.com/run) | tomorrow |\n"
            "## FreeWebNovel (1 novels)\n"
            f"| [The First Order]({FREEWEB}) | all | 1260 | [Available](https://github.com/run) | tomorrow |\n"
        )
        with TemporaryDirectory() as tmp:
            md = Path(tmp) / "DOWNLOADED_NOVELS.md"
            md.write_text(sample, encoding="utf-8")
            records = read_markdown_novels(md)
            self.assertEqual(len(records), 2)
            self.assertEqual(len(select_novels(records, "NovelFull", 0)), 1)
            self.assertEqual(len(select_novels(records, "All", 1)), 1)
            self.assertEqual(len(select_novels(records, "All", 0)), 2)
            self.assertIn(sha256(NOVELFULL.encode()).hexdigest()[:8],
                          cover_basename(records[1]))

    def test_cover_only_saves_image_and_manifest_then_skips_existing(self):
        items = [{
            "website": "NovelFull",
            "title": "Martial World",
            "url": NOVELFULL,
        }]
        html = '<div class="book-img"><img src="https://images.example.org/cover.jpeg"></div>'
        calls = []
        def fetch_page(url):
            calls.append(("page", url))
            return html
        def fetch_image(url, referer):
            calls.append(("image", url))
            return image_bytes()
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "covers"
            dry = download_covers(items, out, dry_run=True)
            self.assertEqual(dry["downloaded"], 0)
            self.assertEqual(calls, [])
            self.assertFalse(out.exists())
            first = download_covers(items, out, confirm_rights=True,
                                    page_fetcher=fetch_page, image_fetcher=fetch_image)
            self.assertEqual(first["downloaded"], 1)
            record = first["results"][0]
            self.assertEqual(record["status"], "downloaded")
            self.assertEqual(record["novel_id"], sha256(NOVELFULL.encode()).hexdigest()[:8])
            self.assertEqual(record["source_url"], NOVELFULL)
            self.assertTrue(record["cover_file"].startswith("NovelFull/martial-world-"))
            self.assertEqual((out / record["cover_file"]).read_bytes(), image_bytes())
            self.assertTrue((out / "covers_manifest.json").is_file())
            before = len(calls)
            again = download_covers(items, out, confirm_rights=True,
                                    page_fetcher=fetch_page, image_fetcher=fetch_image)
            self.assertEqual(again["skipped"], 1)
            self.assertEqual(len(calls), before)
            self.assertEqual(record["cover_file"], again["results"][0]["cover_file"])
            self.assertFalse(list(out.rglob("*.epub")))
            self.assertFalse(list(out.rglob("chapter_*.txt")))

    def test_cover_only_requires_permission_and_preserves_existing_on_failure(self):
        item = [{"website": "NovelFull", "title": "Martial World", "url": NOVELFULL}]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "confirm-rights"):
                download_covers(item, root)
            result = download_covers(
                item, root, confirm_rights=True,
                page_fetcher=lambda _: '<meta property="og:image" content="https://images.test/x.png">',
                image_fetcher=lambda *args: b"invalid",
            )
            self.assertEqual(result["failed"], 1)
            self.assertFalse(list(root.rglob("*.png")))
            self.assertFalse(list(root.rglob("*.jpg")))


if __name__ == "__main__":
    unittest.main()
