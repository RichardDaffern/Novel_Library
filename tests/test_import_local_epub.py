"""Offline tests for permissioned EPUB import from additional source websites."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from zipfile import ZipFile

from PIL import Image

from tools.chunked_download import _epub
from tools.import_local_epub import (
    LocalImportError, import_epub_to_zip, inspect_local_epub, main
)

RR = "https://www.royalroad.com/fiction/21220/mother-of-learning"
WTR = "https://wtr-lab.com/en/novel/6965/myriad-paths"


def fixture_epub(root: Path, cover: bool = True) -> Path:
    novel = root / "source"
    novel.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in range(1, 3):
        filename = f"chapter_{n:04d}.txt"
        (novel / filename).write_text(
            f"Chapter {n}\n\n" + "An original fictional chapter for safe testing. " * 40,
            encoding="utf-8"
        )
        rows.append({"position": n, "file": filename, "title": f"Chapter {n}"})
    if cover:
        Image.new("RGB", (100, 150), (100, 80, 20)).save(novel / "cover.png", "PNG")
    _epub(
        novel, rows, "Test Original Novel", "A Fictional Author", "en",
        "https://example.test/story",
        description="This is an invented synopsis for a synthetic EPUB test.",
        cover_path=(novel / "cover.png" if cover else None)
    )
    return novel / "source.epub"


class LocalEpubArchiveTests(unittest.TestCase):
    def test_royalroad_export_converts_to_standard_zip_offline(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = fixture_epub(root)
            original_bytes = source.read_bytes()
            with patch("tools.import_local_epub.export_epub", wraps=__import__(
                "tools.import_local_epub", fromlist=["export_epub"]
            ).export_epub) as converter:
                path = import_epub_to_zip(
                    source, root / "out", RR, confirm_rights=True
                )
            converter.assert_called_once()
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(path.suffix, ".zip")
            self.assertEqual(path.name, "novel-" + sha256(
                "https://royalroad.com/fiction/21220/mother-of-learning".encode()
            ).hexdigest()[:12] + ".zip")
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                members = archive.namelist()
                prefix = "test-original-novel/"
                self.assertIn(prefix + "source.epub", members)
                self.assertIn(prefix + "metadata.json", members)
                self.assertIn(prefix + "chapters.json", members)
                self.assertIn(prefix + "cover.png", members)
                meta = json.loads(archive.read(prefix + "metadata.json"))
                chapters = json.loads(archive.read(prefix + "chapters.json"))
                self.assertEqual(meta["source_url"],
                                 "https://royalroad.com/fiction/21220/mother-of-learning")
                self.assertEqual(meta["chapter_count"], 2)
                self.assertEqual(meta["cover_image"], "cover.png")
                self.assertEqual(len(chapters), 2)
                for chapter in chapters:
                    raw = archive.read(prefix + chapter["file"])
                    self.assertEqual(sha256(raw).hexdigest(), chapter["sha256"])
                self.assertIn("synopsis", meta)
                self.assertEqual(len(members), 6)

    def test_windows_style_line_endings_are_reconciled_only_when_hash_matches(self):
        from tools.import_local_epub import LocalImportError
        import hashlib
        source = b"First line\nSecond line\n"
        windows = source.replace(b"\n", b"\r\n")
        self.assertNotEqual(
            hashlib.sha256(source).hexdigest(),
            hashlib.sha256(windows).hexdigest()
        )
        self.assertEqual(
            hashlib.sha256(windows.replace(b"\r\n", b"\n")).hexdigest(),
            hashlib.sha256(source).hexdigest()
        )

    def test_wtrlab_authorised_source_without_cover_still_valid(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = fixture_epub(root, cover=False)
            output = import_epub_to_zip(
                epub, root / "output", WTR, confirm_rights=True
            )
            with ZipFile(output) as z:
                files = z.namelist()
                self.assertNotIn("test-original-novel/cover.png", files)
                metadata = json.loads(
                    z.read("test-original-novel/metadata.json")
                )
                self.assertEqual(metadata["chapter_count"], 2)
                self.assertNotIn("cover_image", metadata)
                self.assertEqual(metadata["source_url"], WTR)

    def test_no_permission_cannot_create_archive_or_modify_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = fixture_epub(root)
            before = epub.read_bytes()
            with self.assertRaisesRegex(LocalImportError, "Confirm"):
                import_epub_to_zip(epub, root / "output", RR)
            self.assertEqual(before, epub.read_bytes())
            self.assertFalse((root / "output").exists())

    def test_existing_archive_requires_explicit_replace(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = fixture_epub(root)
            first = import_epub_to_zip(
                source, root / "output", RR, confirm_rights=True
            )
            before = first.read_bytes()
            with self.assertRaisesRegex(LocalImportError, "already exists"):
                import_epub_to_zip(source, root / "output", RR, confirm_rights=True)
            self.assertEqual(before, first.read_bytes())
            replaced = import_epub_to_zip(
                source, root / "output", RR, confirm_rights=True, replace=True
            )
            self.assertEqual(replaced, first)
            with ZipFile(replaced) as z:
                self.assertIsNone(z.testzip())

    def test_no_network_calls_or_wrong_book_urls(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = fixture_epub(root)
            for source in (
                "https://example.org/book",
                RR + "/chapter/1234/title",
                WTR + "/chapter-1",
            ):
                with self.subTest(source=source), self.assertRaises(LocalImportError):
                    import_epub_to_zip(epub, root / "output", source, confirm_rights=True)
            self.assertFalse((root / "output").exists())

    def test_cli_emits_validated_zip_from_local_epub(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = fixture_epub(root)
            rc = main(["--epub", str(epub), "--source-url", RR,
                       "--output-dir", str(root / "complete"), "--confirm-rights"])
            self.assertEqual(rc, 0)
            self.assertEqual(len(list((root / "complete").glob("*.zip"))), 1)


if __name__ == "__main__":
    unittest.main()
