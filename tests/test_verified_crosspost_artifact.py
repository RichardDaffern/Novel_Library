"""Network-free tests of the Scribble Hub Actions archive adapter and workflow."""
import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from tools.chunked_download import _epub
from tools.download_registry import record_download, website_name
from tools.import_local_epub import import_epub_to_zip
from tools.verified_crosspost_artifact import prepare_artifact
from tools.verified_crosspost_download import CrosspostDownloadError


SERIES = "https://www.scribblehub.com/series/445037/the-adventurous-gamer-ninja--daichi-hekima/"
FIRST = "My Second Chance"
SECOND = "Waking up as Daichi Hekima"
REGISTRY = {"minimum_chapters": 2, "first_chapter_title": FIRST,
            "chapter_checkpoints": [{"position": 2, "title": SECOND}]}


def make_archive(root: Path, *, source_url: str = SERIES) -> Path:
    source = root / "source"
    source.mkdir()
    rows = []
    for number, title in enumerate([FIRST, SECOND], 1):
        filename = f"chapter_{number:05d}.txt"
        body = (f"Wholly invented example for chapter {number}. " * 40).strip()
        content = f"{title}\n\n{body}\n".encode("utf-8")
        (source / filename).write_bytes(content)
        rows.append({"position": number, "chapter_number": number,
                     "title": title, "file": filename,
                     "sha256": sha256(content).hexdigest(),
                     "word_count": len(body.split())})
    _epub(source, rows, "The Adventurous Gamer Ninja - Daichi Hekima",
          "MonkWithAPen", "en", source_url)
    return import_epub_to_zip(
        source / "source.epub", root / "zips", source_url, confirm_rights=True
    )


class VerifiedActionsArtifactTests(unittest.TestCase):
    def prepare(self, archive: Path, output: Path, source_url: str = SERIES):
        with patch("tools.verified_crosspost_artifact._verified_record",
                   return_value=(SERIES, "445037", REGISTRY)):
            return prepare_artifact(archive, output, source_url)

    def test_actions_folder_and_metadata_registry_contract(self):
        with TemporaryDirectory() as root:
            tmp = Path(root)
            archive = make_archive(tmp)
            with patch("socket.create_connection",
                       side_effect=AssertionError("No networking")):
                book = self.prepare(archive, tmp / "downloads")
            self.assertTrue((book / "source.epub").is_file())
            metadata = json.loads((book / "metadata.json").read_text(encoding="utf-8"))
            rows = json.loads((book / "chapters.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_url"], SERIES)
            self.assertEqual([r["position"] for r in rows], [1, 2])
            for row in rows:
                self.assertEqual(sha256((book / row["file"]).read_bytes()).hexdigest(),
                                 row["sha256"])
            registry = {"version": 1, "novels": []}
            entry = record_download(
                registry, SERIES, "", tmp / "downloads",
                "123", "https://github.com/example/repo/actions/runs/123",
                "456",
            )
            self.assertEqual(entry["chapter_count"], 2)
            self.assertEqual(entry["range"], "all")
            self.assertEqual(website_name(SERIES), "Scribble Hub")

    def test_bad_archive_members_do_not_publish(self):
        with TemporaryDirectory() as root:
            tmp = Path(root)
            archive = make_archive(tmp)
            with ZipFile(archive, "a", compression=ZIP_DEFLATED) as zip_file:
                zip_file.writestr("malicious/../extra.txt", b"not part of novel")
            with self.assertRaises(CrosspostDownloadError):
                self.prepare(archive, tmp / "downloads")
            self.assertFalse((tmp / "downloads").exists())

    def test_wrong_book_metadata_rejected(self):
        with TemporaryDirectory() as root:
            tmp = Path(root)
            archive = make_archive(
                tmp,
                source_url="https://www.scribblehub.com/series/445038/other-work/"
            )
            with self.assertRaisesRegex(CrosspostDownloadError, "source URL"):
                self.prepare(archive, tmp / "downloads")
            self.assertFalse((tmp / "downloads").exists())

    def test_existing_output_preserved_without_replacing(self):
        with TemporaryDirectory() as root:
            tmp = Path(root)
            archive = make_archive(tmp)
            first = self.prepare(archive, tmp / "downloads")
            previous = (first / "source.epub").read_bytes()
            with self.assertRaisesRegex(CrosspostDownloadError, "already exists"):
                self.prepare(archive, tmp / "downloads")
            self.assertEqual((first / "source.epub").read_bytes(), previous)

    def test_actions_manual_only_and_does_not_modify_unified_bulk(self):
        workflow = Path(".github/workflows/scribblehub-download.yml").read_text(
            encoding="utf-8"
        )
        bulk = Path(".github/workflows/library-bulk-download.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: Scribble Hub - Download", workflow)
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("workflow_call:", workflow)
        self.assertIn("      confirm_rights:", workflow)
        self.assertIn("        default: false", workflow)
        self.assertIn("tools.verified_crosspost_download", workflow)
        self.assertIn("id: download", workflow)
        self.assertIn("Explain FicHub export failure", workflow)
        self.assertIn("tools.verified_crosspost_artifact", workflow)
        self.assertIn("tools.download_registry check", workflow)
        self.assertIn("tools.publish_registry", workflow)
        self.assertIn("upload-artifact@", workflow)
        self.assertIn("path: downloads/", workflow)
        self.assertIn("retention-days: 7", workflow)
        self.assertIn("if-no-files-found: error", workflow)
        self.assertIn("          ref: main", workflow)
        self.assertNotIn("ScribbleHub", bulk)
        self.assertNotIn("scribblehub-download.yml", bulk)


if __name__ == "__main__":
    unittest.main()
