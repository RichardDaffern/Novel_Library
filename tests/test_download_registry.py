import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.download_registry import (
    already_available, canonical_url, main, normalise_range,
    read_registry, record_download, write_registry,
)


NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)


def item(chapter_range, expiry_hours=24, chapter_count=10):
    return {
        "range": chapter_range,
        "status": "complete",
        "chapter_count": chapter_count,
        "expires_at_utc": (NOW + timedelta(hours=expiry_hours)).isoformat(),
    }


def registry_with(*records):
    return {"version": 1, "novels": [{
        "url": "https://novelfull.com/sample.html",
        "title": "Sample",
        "author": "",
        "downloads": list(records),
    }]}


class DownloadRegistryTests(unittest.TestCase):
    def test_canonical_url_and_range(self):
        self.assertEqual(
            canonical_url(" HTTPS://NOVELFULL.COM/sample.html#toc "),
            "https://novelfull.com/sample.html",
        )
        self.assertEqual(normalise_range("  3 - 5  "), "3-5")
        self.assertEqual(normalise_range(""), "all")
        self.assertRaises(ValueError, normalise_range, "0-2")
        self.assertRaises(ValueError, normalise_range, "5-4")
        self.assertRaises(ValueError, canonical_url, "http://example.com/novel")

    def test_full_book_prevents_repeat_and_subranges(self):
        data = registry_with(item("all"))
        self.assertTrue(already_available(data, "https://novelfull.com/sample.html", "", now=NOW))
        self.assertTrue(already_available(data, "https://novelfull.com/sample.html", "3-5", now=NOW))

    def test_exact_and_adjacent_ranges_are_covered(self):
        data = registry_with(item("1-30"), item("31-60"))
        self.assertTrue(already_available(data, "https://novelfull.com/sample.html", "10-50", now=NOW))
        self.assertFalse(already_available(data, "https://novelfull.com/sample.html", "1-61", now=NOW))
        self.assertFalse(already_available(data, "https://novelfull.com/sample.html", "", now=NOW))

    def test_uncovered_gaps_allow_download(self):
        data = registry_with(item("1-30"), item("32-60"))
        self.assertFalse(already_available(data, "https://novelfull.com/sample.html", "1-60", now=NOW))
        self.assertFalse(already_available(data, "https://novelfull.com/different.html", "1-30", now=NOW))

    def test_expired_artifact_does_not_block_repeat(self):
        data = registry_with(item("all", expiry_hours=-1))
        self.assertFalse(already_available(data, "https://novelfull.com/sample.html", "", now=NOW))

    def test_cli_force_overrides_existing_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            registry_file = base / "registry.json"
            registry_file.write_text(json.dumps(registry_with(item("all", expiry_hours=8760))))
            gh_output = base / "outputs.txt"
            with patch.dict("os.environ", {"GITHUB_OUTPUT": str(gh_output)}):
                result = main(["check", "--registry", str(registry_file), "--url",
                               "https://novelfull.com/sample.html"])
                self.assertEqual(result, 0)
                self.assertIn("skip=true", gh_output.read_text())
                result = main(["check", "--registry", str(registry_file), "--url",
                               "https://novelfull.com/sample.html", "--force"])
                self.assertEqual(result, 0)
                self.assertIn("skip=false", gh_output.read_text())

    def test_record_requires_real_epub_and_individual_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            book = base / "downloads" / "sample"
            book.mkdir(parents=True)
            url = "https://novelfull.com/sample.html"
            (book / "source.epub").write_bytes(b"synthetic epub for registry test")
            (book / "chapter_0001.txt").write_text("First chapter body\n", encoding="utf-8")
            (book / "chapter_0002.txt").write_text("Second chapter body\n", encoding="utf-8")
            (book / "metadata.json").write_text(json.dumps({
                "title": "Sample", "author": "Anon", "source_url": url, "chapter_count": 2
            }))
            (book / "chapters.json").write_text(json.dumps([
                {"position": 1, "file": "chapter_0001.txt"},
                {"position": 2, "file": "chapter_0002.txt"},
            ]))
            registry = {"version": 1, "novels": []}
            entry = record_download(
                registry, url, "1-2", base / "downloads",
                "9999", "https://github.com/owner/repo/actions/artifacts/500",
                "500", now=NOW,
            )
            self.assertEqual(entry["chapter_count"], 2)
            self.assertEqual(entry["range"], "1-2")
            self.assertEqual(registry["novels"][0]["author"], "Anon")
            (book / "chapter_0002.txt").unlink()
            with self.assertRaisesRegex(ValueError, "Missing chapter file"):
                record_download(registry, url, "1-2", base / "downloads",
                                "9999", "url", "500", now=NOW)

    def test_markdown_tracks_artifact_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = registry_with(item("1-2"))
            data["novels"][0]["downloads"][0]["artifact_url"] = "https://github.com/example"
            write_registry(data, base / "novels.json", base / "novels.md")
            self.assertIn("Sample", (base / "novels.md").read_text())
            self.assertIn("https://github.com/example", (base / "novels.md").read_text())
            self.assertEqual(read_registry(base / "novels.json")["version"], 1)

    def test_existing_completed_downloads_backfilled(self):
        data = read_registry(Path("downloaded_novels.json"))
        titles = {x["title"] for x in data["novels"]}
        self.assertTrue({"She Is From the Countryside", "I Can Track Everything", "The World Online"} <= titles)


if __name__ == "__main__":
    unittest.main()
