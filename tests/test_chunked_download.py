"""Offline regression tests for chunked downloads and final EPUB assembly."""

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from unittest.mock import patch
from types import SimpleNamespace

from novel_downloader import epub_chapters
from tools.chunked_download import (
    SYNTHETIC_URL, assemble, chapter_plan, chapter_count_from_metadata,
    discover_count, identity, validate_piece,
    _epub,
)

URL = "https://example.org/very-long-story.html"


def make_piece(root: Path, url: str, key: str, first: int, last: int) -> Path:
    folder = root / f"chapter-batch-{key}-{first:05d}-{last:05d}"
    book = folder / "book"
    book.mkdir(parents=True)
    rows = []
    for position in range(first, last + 1):
        filename = f"chapter_{position:04d}.txt"
        text = f"Chapter {position}\n\nChapter {position} paragraph with meaningful synthetic content to test EPUB assembly.\n"
        (book / filename).write_text(text, encoding="utf-8")
        rows.append({
            "position": position, "chapter_number": position,
            "title": f"Chapter {position}", "file": filename,
            "word_count": len(text.split()),
            "sha256": sha256(text.encode()).hexdigest(),
        })
    (book / "chapters.json").write_text(json.dumps(rows), encoding="utf-8")
    (book / "metadata.json").write_text(json.dumps({
        "source_url": url, "chapter_count": len(rows),
        "title": "A Synthetic Very Long Story",
        "author": "Synthetic Test Author", "language": "en",
    }), encoding="utf-8")
    (book / "source.epub").write_bytes(b"synthetic batch archive fixture")
    (folder / "part.json").write_text(json.dumps({
        "version": 1, "url": url, "key": key, "start": first, "end": last,
    }), encoding="utf-8")
    return folder


class ChapterBatchTests(unittest.TestCase):
    def test_fanficfare_formatted_chapter_counts(self):
        for value in ("4,035", "4035", 4035, " 4,035 "):
            with self.subTest(value=value):
                count = chapter_count_from_metadata({"numChapters": value})
                self.assertEqual(count, 4035)
                self.assertEqual(len(chapter_plan(URL, count)["pieces"]), 21)

    def test_fallback_chapter_list_count(self):
        self.assertEqual(
            chapter_count_from_metadata({"zchapters": [{"url": "a"}, {"url": "b"}]}),
            2,
        )

    def test_invalid_chapter_counts_fail_before_starting_download(self):
        for value in ("4,03", "4,035 chapters", "unknown", "1.5", "", 0, -1, None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                chapter_count_from_metadata({"numChapters": value})
        with self.assertRaises(ValueError):
            chapter_count_from_metadata({})

    def test_live_discovery_json_passes_formatted_count_to_planner(self):
        with patch("tools.chunked_download.subprocess.run",
                   return_value=SimpleNamespace(stdout='{"numChapters":"4,035"}')) as runner:
            count = discover_count(URL)
        self.assertEqual(count, 4035)
        self.assertEqual(chapter_plan(URL, count)["pieces"][-1]["end"], 4035)
        self.assertTrue(runner.call_args.kwargs["check"])

    def test_four_thousand_chapters_fit_in_bounded_independent_jobs(self):
        plan = chapter_plan(URL, 4035)
        self.assertEqual(len(plan["pieces"]), 21)
        self.assertEqual(plan["pieces"][0]["start"], 1)
        self.assertEqual(plan["pieces"][0]["end"], 200)
        self.assertEqual(plan["pieces"][-1]["start"], 4001)
        self.assertEqual(plan["pieces"][-1]["end"], 4035)
        self.assertEqual(plan["pieces"][0]["name"],
                         f"chapter-batch-{identity(URL)}-00001-00200")

    def test_inclusive_requested_range_kept(self):
        plan = chapter_plan(URL, 4000, "251-500", chunk_size=200)
        self.assertEqual([(p["start"], p["end"]) for p in plan["pieces"]],
                         [(251, 450), (451, 500)])
        self.assertEqual((plan["first"], plan["last"]), (251, 500))

    def test_rejects_bad_counts_or_requested_out_of_bounds_ranges(self):
        for count in (-1, 0):
            with self.subTest(count=count), self.assertRaises(ValueError):
                chapter_plan(URL, count)
        with self.assertRaisesRegex(ValueError, "contains only"):
            chapter_plan(URL, 9, "1-10")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            chapter_plan(URL, 50000, chunk_size=200)

    def test_verified_batch_rejects_corruption_and_wrong_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder = make_piece(root, URL, identity(URL), 1, 2)
            data = validate_piece(folder, URL, identity(URL), 1, 2)
            self.assertEqual(len(data["chapters"]), 2)
            self.assertRaises(ValueError, validate_piece, folder, URL, identity(URL), 1, 3)
            (folder / "book/chapter_0002.txt").write_text("CHANGED")
            with self.assertRaises(ValueError):
                validate_piece(folder, URL, identity(URL), 1, 2)

    def test_two_batches_assemble_complete_nonoverlapping_epub(self):
        plan = chapter_plan(URL, 4, "1-4", chunk_size=2)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            parts = root / "parts"
            make_piece(parts, URL, plan["key"], 1, 2)
            make_piece(parts, URL, plan["key"], 3, 4)
            book = assemble(plan, parts, root / "downloads")
            rows = json.loads((book / "chapters.json").read_text(encoding="utf-8"))
            self.assertEqual([r["position"] for r in rows], [1, 2, 3, 4])
            self.assertTrue(all((book / r["file"]).is_file() for r in rows))
            metadata, unpacked = epub_chapters(book / "source.epub")
            self.assertEqual(metadata["title"], "A Synthetic Very Long Story")
            self.assertEqual(len(unpacked), 4)
            self.assertIn("Chapter 4 paragraph", unpacked[-1]["text"])
            with zipfile.ZipFile(book / "source.epub") as archive:
                self.assertEqual(archive.namelist()[0], "mimetype")
                self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
                self.assertEqual(archive.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)

    def test_missing_batch_does_not_produce_partial_complete_novel(self):
        plan = chapter_plan(URL, 4, "1-4", chunk_size=2)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_piece(root / "parts", URL, plan["key"], 1, 2)
            with self.assertRaises(FileNotFoundError):
                assemble(plan, root / "parts", root / "downloads")
            self.assertFalse((root / "downloads/very-long-story/source.epub").exists())

    def test_reordering_or_duplicate_positions_is_rejected(self):
        plan = chapter_plan(URL, 4, "1-4", chunk_size=2)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = make_piece(root, URL, plan["key"], 1, 2)
            make_piece(root, URL, plan["key"], 3, 4)
            rows = json.loads((first / "book/chapters.json").read_text())
            rows[1]["position"] = 1
            (first / "book/chapters.json").write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                assemble(plan, root, root / "out")

    def test_complete_batch_is_recovered_without_redownloading(self):
        import shutil
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.chunked_download import reuse_complete_piece, fetch_piece
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_piece(root / "cached", URL, identity(URL), 1, 2)
            destination = root / "restored"
            artifact = {"name": f"chapter-batch-{identity(URL)}-00001-00002",
                        "workflow_run": {"id": 321}}
            calls = []

            def simulate_gh(args, **kwargs):
                calls.append(args)
                output = Path(args[args.index("-D") + 1])
                shutil.copytree(source, output, dirs_exist_ok=True)
                return SimpleNamespace(returncode=0)

            with patch("tools.chunked_download._prior_artifacts", return_value=[artifact]):
                with patch("tools.chunked_download.subprocess.run", side_effect=simulate_gh):
                    fetch_piece(URL, identity(URL), 1, 2, destination, root / "scratch")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:3], ["gh", "run", "download"])
            self.assertEqual(len(validate_piece(destination, URL, identity(URL), 1, 2)["chapters"]), 2)

    def test_synthetic_url_identity_is_stable(self):
        plan = chapter_plan(SYNTHETIC_URL, 9, "3-4")
        self.assertEqual(plan["pieces"][0]["name"],
                         f"chapter-batch-{identity(SYNTHETIC_URL)}-00003-00004")


if __name__ == "__main__":
    unittest.main()
