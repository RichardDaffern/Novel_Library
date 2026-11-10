"""Offline tests for repairing historical ZIP/EPUB synopsis without touching chapters."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools.chunked_download import _epub
from tools.repair_synopsis import (
    SynopsisError, archive_info, clean_description, main,
    patch_epub, read_epub_description, repair, public_novelfull_synopsis,
)

SOURCE = "https://novelfull.com/synthetic-villain.html"
DESCRIPTION = ("A clever protagonist receives an unusual choice system, "
               "and uses it to reshape the world of the original novel.")


def make_novel_zip(root: Path):
    book = root / "book"
    book.mkdir()
    (book / "chapter_00001.txt").write_text(
        "Chapter 1\n\nEntirely invented prose with some extra detail for a unit test.\n",
        encoding="utf-8",
    )
    rows = [{"position": 1, "title": "Chapter 1", "file": "chapter_00001.txt"}]
    _epub(book, rows, "Synthetic Villain", "Test Author", "en", SOURCE)
    original = root / "novel-123.zip"
    with ZipFile(original, "w") as archive:
        archive.writestr("synthetic-villain/metadata.json", json.dumps({
            "title": "Synthetic Villain", "author": "Test Author",
            "source_url": SOURCE, "chapter_count": 1,
        }))
        archive.writestr("synthetic-villain/chapters.json", json.dumps(rows))
        archive.write(book / "source.epub", "synthetic-villain/source.epub")
        archive.write(book / "chapter_00001.txt", "synthetic-villain/chapter_00001.txt")
    return original


class SynopsisRepairTests(unittest.TestCase):
    def test_description_cleaning_keeps_literal_angle_brackets(self):
        self.assertEqual(clean_description(DESCRIPTION + " <special>"), DESCRIPTION + " <special>")
        self.assertEqual(
            clean_description("<div><p>" + DESCRIPTION + "</p></div>"),
            DESCRIPTION,
        )
        with self.assertRaises(SynopsisError):
            clean_description("short")

    def test_original_zip_unchanged_and_description_added_to_both_formats(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            before = original.read_bytes()
            status = repair(original, root / "repaired", provided=DESCRIPTION)
            self.assertIn("saved", status)
            self.assertEqual(original.read_bytes(), before)
            corrected = root / "repaired" / original.name
            with ZipFile(original) as old, ZipFile(corrected) as new:
                self.assertEqual(new.namelist(), old.namelist())
                self.assertIsNone(new.testzip())
                for name in ("synthetic-villain/chapter_00001.txt",
                             "synthetic-villain/chapters.json"):
                    self.assertEqual(new.read(name), old.read(name))
                metadata = json.loads(new.read("synthetic-villain/metadata.json"))
                self.assertEqual(metadata["description"], DESCRIPTION)
                self.assertEqual(metadata["synopsis"], DESCRIPTION)
                self.assertEqual(metadata["chapter_count"], 1)
                self.assertEqual(
                    read_epub_description(new.read("synthetic-villain/source.epub"))[1],
                    DESCRIPTION,
                )

    def test_uses_existing_source_description_without_network(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            with ZipFile(original) as z:
                epub = z.read("synthetic-villain/source.epub")
            patched = patch_epub(epub, DESCRIPTION)
            with ZipFile(original) as old:
                members = [(i, old.read(i)) for i in old.infolist()]
            with ZipFile(original, "w") as new:
                for entry, data in members:
                    new.writestr(entry, patched if entry.filename.endswith("/source.epub") else data)
            result = repair(
                original, root / "out",
                fetcher=lambda _: self.fail("Public website should not be contacted"),
            )
            self.assertIn("saved", result)
            with ZipFile(root / "out" / original.name) as z:
                metadata = json.loads(z.read("synthetic-villain/metadata.json"))
            self.assertEqual(metadata["description"], DESCRIPTION)

    def test_one_public_metadata_lookup_if_synopsis_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            calls = []
            def fetch(url):
                calls.append(url)
                return DESCRIPTION
            repair(original, root / "out", fetcher=fetch)
            self.assertEqual(calls, [SOURCE])

    def test_existing_copy_mode_never_overwrites_existing_output(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            before = original.read_bytes()
            self.assertIn("saved", repair(original, root / "out", provided=DESCRIPTION))
            saved = (root / "out" / original.name).read_bytes()
            self.assertIn("already exists", repair(original, root / "out", provided=DESCRIPTION))
            self.assertEqual(saved, (root / "out" / original.name).read_bytes())
            self.assertEqual(before, original.read_bytes())

    def test_atomic_in_place_overwrite_preserves_every_chapter_and_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            with ZipFile(original) as existing:
                member_before = {
                    name: existing.read(name)
                    for name in existing.namelist()
                    if not name.endswith("/metadata.json") and not name.endswith("/source.epub")
                }
            status = repair(original, provided=DESCRIPTION)
            self.assertIn("replaced original", status)
            self.assertTrue(original.is_file())
            with ZipFile(original) as corrected:
                self.assertIsNone(corrected.testzip())
                for name, content in member_before.items():
                    self.assertEqual(corrected.read(name), content)
                metadata = json.loads(corrected.read("synthetic-villain/metadata.json"))
                self.assertEqual(metadata["description"], DESCRIPTION)
                self.assertEqual(metadata["synopsis"], DESCRIPTION)
                epub = corrected.read("synthetic-villain/source.epub")
                self.assertEqual(read_epub_description(epub)[1], DESCRIPTION)
            self.assertFalse((root / "Synopsis_Repaired").exists())
            self.assertEqual(list(root.glob(".synopsis-*.zip")), [])
            self.assertIn("synopsis already complete", repair(original))

    def test_validation_failure_keeps_original_unchanged_and_deletes_staged_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            before = original.read_bytes()
            with patch("tools.repair_synopsis._verify_repair",
                       side_effect=SynopsisError("simulated checksum mismatch")):
                with self.assertRaisesRegex(SynopsisError, "checksum mismatch"):
                    repair(original, provided=DESCRIPTION)
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(list(root.glob(".synopsis-*.zip")), [])

    def test_replace_failure_keeps_original_and_removes_temp_zip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            before = original.read_bytes()
            with patch("tools.repair_synopsis.os.replace",
                       side_effect=PermissionError("file is locked")):
                with self.assertRaisesRegex(PermissionError, "locked"):
                    repair(original, provided=DESCRIPTION)
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(list(root.glob(".synopsis-*.zip")), [])

    def test_external_modification_aborts_before_replacement(self):
        import os

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            def metadata_lookup(_):
                current = original.stat()
                os.utime(original, ns=(current.st_atime_ns, current.st_mtime_ns - 1_000_000_000))
                return DESCRIPTION
            with self.assertRaisesRegex(SynopsisError, "changed during repair"):
                repair(original, fetcher=metadata_lookup)
            with ZipFile(original) as z:
                self.assertNotIn("description", json.loads(
                    z.read("synthetic-villain/metadata.json")))
            self.assertEqual(list(root.glob(".synopsis-*.zip")), [])

    def test_cli_apply_defaults_to_overwrite_not_a_subfolder(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            rc = main([
                "--zip", str(original), "--description", DESCRIPTION, "--apply"
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(original.is_file())
            self.assertEqual(archive_info(original)[4], DESCRIPTION)
            self.assertEqual(len(list(root.glob("*.zip"))), 1)
            self.assertFalse((root / "Synopsis_Repaired").exists())

    def test_rejects_unapproved_source_site_for_automatic_lookup(self):
        with self.assertRaises(SynopsisError):
            public_novelfull_synopsis("https://example.org/test")
        with self.assertRaises(SynopsisError):
            public_novelfull_synopsis("https://novelfull.com/chapter.html?token=1")

    def test_cli_dry_run_does_not_write_zip_or_contact_website(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = make_novel_zip(root)
            with patch("tools.repair_synopsis.public_novelfull_synopsis",
                       side_effect=AssertionError("No HTTP during dry-run")):
                self.assertEqual(main(["--zip", str(original)]), 0)
            self.assertFalse((root / "Synopsis_Repaired").exists())


if __name__ == "__main__":
    unittest.main()
