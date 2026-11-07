"""Offline coverage for the separate multi-novel GitHub Actions workflow."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools.bulk_download import (
    create_plan, main, parse_novel_urls, run_batch, storage_key,
    summary, validate_and_record,
)


URL1 = "https://example.org/first-novel.html"
URL2 = "https://example.org/second-novel.html"
URL3 = "https://other.example.org/first-novel.html"


def registry_with_download(url: str = URL1, chapter_range: str = "all"):
    return {"version": 1, "novels": [{
        "url": url, "title": "First Novel", "downloads": [{
            "range": chapter_range,
            "status": "complete",
            "expires_at_utc": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        }],
    }]}


class BulkDownloadTests(unittest.TestCase):
    def test_parses_newline_comma_and_space_separated_links(self):
        values = f"{URL1}\n {URL2}, {URL3} {URL1}"
        self.assertEqual(parse_novel_urls(values), [URL1, URL2, URL3])

    def test_limits_unique_novels_and_rejects_bad_urls(self):
        with self.assertRaisesRegex(ValueError, "Maximum 2"):
            parse_novel_urls(f"{URL1} {URL2} {URL3}", limit=2)
        for bad in ("", "file:///tmp/text", "http://example.org/title"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_novel_urls(bad)

    def test_duplicate_registry_checked_before_download(self):
        plan = create_plan(registry_with_download(), f"{URL1}\n{URL2}")
        self.assertEqual(len(plan["planned"]), 1)
        self.assertEqual(plan["planned"][0]["url"], URL2)
        self.assertEqual(len(plan["skipped"]), 1)
        self.assertEqual(plan["skipped"][0]["url"], URL1)

    def test_force_includes_previously_downloaded(self):
        plan = create_plan(registry_with_download(), URL1, force=True)
        self.assertEqual(len(plan["planned"]), 1)
        self.assertFalse(plan["skipped"])

    def test_range_awareness_and_unique_storage_paths(self):
        self.assertNotEqual(storage_key(URL1, "all"), storage_key(URL1, "1-2"))
        self.assertNotEqual(storage_key(URL1, "all"), storage_key(URL3, "all"))
        plan = create_plan(registry_with_download(URL1, "1-10"), f"{URL1} {URL2}", "5-8")
        self.assertEqual([x["url"] for x in plan["skipped"]], [URL1])
        self.assertEqual([x["url"] for x in plan["planned"]], [URL2])

    def test_plan_writes_output_and_skips_unnecessary_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.json"
            registry.write_text(json.dumps(registry_with_download()))
            gh_output = root / "output.txt"
            with patch.dict("os.environ", {"GITHUB_OUTPUT": str(gh_output)}):
                result = main(["plan", "--registry", str(registry),
                               "--urls", URL1,
                               "--plan-file", str(root / "plan.json"),
                               "--results-file", str(root / "result.json")])
            self.assertEqual(result, 0)
            self.assertIn("has_work=false", gh_output.read_text())
            self.assertEqual(len(json.loads((root / "result.json").read_text())["skipped"]), 1)

    def test_continues_after_one_failure_and_preserves_result(self):
        plan = create_plan({"version": 1, "novels": []}, f"{URL1} {URL2} {URL3}", "1-2")
        calls = []

        def invoke(command, **_kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=1 if URL2 in command else 0)

        with tempfile.TemporaryDirectory() as temp:
            result = run_batch(plan, Path(temp), clock=lambda: 0, invoke=invoke)
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(result["completed"]), 2)
            self.assertEqual(len(result["failed"]), 1)
            self.assertIn("--chapter-range", calls[0])
            self.assertIn("--confirm-rights", calls[0])
            self.assertIn("--output-dir", calls[0])
            self.assertIn(URL3, calls[2])
            self.assertEqual(len({item["folder"] for item in plan["planned"]}), 3)
            self.assertIn("Failed", summary(result))

    def test_failure_does_not_block_registry_of_successful_novels(self):
        plan = create_plan({"version": 1, "novels": []}, f"{URL1} {URL2}", "1-2")
        results = {"version": 1, "completed": [plan["planned"][0]],
                   "failed": [plan["planned"][1]], "skipped": []}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book = root / plan["planned"][0]["folder"] / "first-novel-chapters-0001-0002"
            book.mkdir(parents=True)
            (book / "source.epub").write_bytes(b"fake synthetic EPUB")
            (book / "chapter_0001.txt").write_text("chapter one")
            (book / "chapter_0002.txt").write_text("chapter two")
            (book / "metadata.json").write_text(json.dumps({
                "title": "First Novel", "author": "Test Author",
                "source_url": URL1, "chapter_count": 2,
            }))
            (book / "chapters.json").write_text(json.dumps([
                {"position": 1, "file": "chapter_0001.txt"},
                {"position": 2, "file": "chapter_0002.txt"},
            ]))
            registry = {"version": 1, "novels": []}
            count = validate_and_record(
                registry, results, root, "4242", "5000",
                "https://github.com/example/repo/actions/artifacts/5000",
            )
            self.assertEqual(count, 1)
            self.assertEqual(len(registry["novels"]), 1)
            self.assertEqual(registry["novels"][0]["downloads"][0]["range"], "1-2")
            self.assertEqual(registry["novels"][0]["downloads"][0]["chapter_count"], 2)
            self.assertNotIn(URL2, json.dumps(registry))

    def test_report_flags_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "results.json"
            output.write_text(json.dumps({"completed": [{"url": URL1, "range": "all"}],
                                          "skipped": [], "failed": [{"url": URL2, "range": "all"}]}))
            self.assertEqual(main(["report", "--results-file", str(output)]), 1)
            output.write_text(json.dumps({"completed": [], "skipped": [],
                                          "failed": []}))
            self.assertEqual(main(["report", "--results-file", str(output)]), 0)


if __name__ == "__main__":
    unittest.main()
