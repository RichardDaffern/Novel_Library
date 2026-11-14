"""Offline tests proving partial bulk failure preserves successfully completed ZIPs."""
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from tools.bulk_recovery import recover
from tools.chunked_download import _epub


NOVELFULL = "https://novelfull.com/a-valid-book.html"
FREEWEBNOVEL = "https://freewebnovel.com/novel/a-failed-book"
SCRIBBLE = "https://www.scribblehub.com/series/445037/the-adventurous-gamer-ninja--daichi-hekima/"


def plan():
    return {
        "version": 1,
        "selected_count": 3,
        "groups": {
            "NovelFull": [{
                "novel_url": NOVELFULL, "chapter_range": "", "title": "A Valid Book",
            }],
            "FreeWebNovel": [{
                "novel_url": FREEWEBNOVEL, "chapter_range": "", "title": "A Failed Book",
            }],
            "Scribble Hub": [{
                "novel_url": SCRIBBLE, "chapter_range": "", "title": "The Adventurous Gamer",
            }],
        },
        "skipped": [],
    }


def create_child(folder: Path, artefact: str, source: str,
                 *, invalid_sha=False, extra=False) -> Path:
    book = folder / artefact / "a-valid-book"
    book.mkdir(parents=True)
    rows = []
    for index in range(1, 3):
        name = f"chapter_{index:05d}.txt"
        title = f"Synthetic Chapter {index}"
        body = (f"Completely invented test-only chapter {index}. " * 12).strip()
        data = f"{title}\n\n{body}\n".encode("utf-8")
        (book / name).write_bytes(data)
        rows.append({
            "position": index, "chapter_number": index,
            "title": title, "file": name, "word_count": len(body.split()),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    _epub(book, rows, "A Valid Book", "Synthetic Test", "en", source)
    if invalid_sha:
        rows[1]["sha256"] = "0" * 64
    (book / "metadata.json").write_text(json.dumps({
        "source_url": source, "title": "A Valid Book",
        "author": "Synthetic Test", "chapter_count": 2,
    }), encoding="utf-8")
    (book / "chapters.json").write_text(json.dumps(rows), encoding="utf-8")
    if extra:
        (book / "unexpected.txt").write_text("should be rejected", encoding="utf-8")
    return book


class BulkRecoveryTests(unittest.TestCase):
    def test_two_successes_one_failure_produce_two_complete_portable_zips(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            artifacts = root / "artifacts"
            first = create_child(artifacts, "novel-123-first", NOVELFULL)
            second = create_child(artifacts, "novel-123-third", SCRIBBLE)
            report = recover(plan(), artifacts, root / "recovery", run_id="123")
            self.assertEqual(len(report["recovered"]), 2)
            self.assertEqual(len(report["missing_or_failed"]), 1)
            self.assertEqual(report["missing_or_failed"][0]["url"], FREEWEBNOVEL)
            self.assertTrue((first / "source.epub").is_file())
            self.assertTrue((second / "source.epub").is_file())
            self.assertEqual(len(list((root / "recovery").glob("novel-*.zip"))), 2)
            for item in report["recovered"]:
                path = root / "recovery" / item["filename"]
                with ZipFile(path) as archive:
                    self.assertIsNone(archive.testzip())
                    names = archive.namelist()
                    self.assertTrue(any(name.endswith("/source.epub") for name in names))
                    self.assertTrue(any(name.endswith("/metadata.json") for name in names))
                    self.assertEqual(sum(name.endswith(".txt") for name in names), 2)
            self.assertEqual(
                json.loads((root / "recovery" / "bulk_recovery_manifest.json").read_text())["recovered"],
                report["recovered"],
            )

    def test_later_corrupt_book_cannot_delete_earlier_successful_book(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            artifacts = root / "artifacts"
            create_child(artifacts, "novel-123-a-good", NOVELFULL)
            create_child(artifacts, "novel-123-z-bad", SCRIBBLE, invalid_sha=True)
            report = recover(plan(), artifacts, root / "out", run_id="123")
            self.assertEqual(len(report["recovered"]), 1)
            self.assertEqual(len(report["rejected_artifacts"]), 1)
            self.assertEqual(len(list((root / "out").glob("novel-*.zip"))), 1)
            self.assertEqual({x["url"] for x in report["missing_or_failed"]},
                             {SCRIBBLE.rstrip("/"), FREEWEBNOVEL})

    def test_unknown_artifact_and_unrecognised_run_id_are_not_published(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            artifacts = root / "artifacts"
            create_child(artifacts, "novel-999-other-run", NOVELFULL)
            create_child(artifacts, "novel-123-unexpected", "https://novelfull.com/unrelated.html")
            report = recover(plan(), artifacts, root / "out", run_id="123")
            self.assertEqual(report["recovered"], [])
            self.assertEqual(len(report["missing_or_failed"]), 3)
            self.assertEqual(len(report["rejected_artifacts"]), 1)
            self.assertFalse(list((root / "out").glob("novel-*.zip")))
            self.assertTrue((root / "out" / "bulk_recovery_manifest.json").exists())

    def test_bad_files_do_not_publish_incomplete_novel(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            create_child(root / "artifacts", "novel-123-corrupt", NOVELFULL, extra=True)
            result = recover(plan(), root / "artifacts", root / "out", run_id="123")
            self.assertEqual(len(result["recovered"]), 0)
            self.assertEqual(len(result["rejected_artifacts"]), 1)
            self.assertEqual(len(list((root / "out").glob("novel-*.zip"))), 0)

    def test_no_successes_still_produce_manifest_for_failed_bulk_run(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            result = recover(plan(), root / "no-artifacts", root / "out", run_id="123")
            self.assertEqual(len(result["missing_or_failed"]), 3)
            self.assertEqual(result["recovered"], [])
            self.assertTrue((root / "out" / "bulk_recovery_manifest.json").is_file())
            self.assertFalse(list((root / "out").glob("novel-*.zip")))

    def test_previously_created_recovery_folder_is_never_overwritten(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out"
            output.mkdir()
            (output / "keep.txt").write_text("important")
            with self.assertRaisesRegex(ValueError, "already exists"):
                recover(plan(), root / "any", output, run_id="123")
            self.assertEqual((output / "keep.txt").read_text(), "important")


if __name__ == "__main__":
    unittest.main()
