"""Offline tests for site-grouped registry and name-based batch selection."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.download_registry import website_name, write_registry, read_registry
from tools.library_bulk import (
    catalogue_entries, main, parse_names, read_curated, selection_plan,
)

NOVELFULL = "https://novelfull.com/the-world-online.html"
COMMA = "https://novelfull.com/please-i-really-didnt-want-to-fall-in-love-with-my-master.html"
FREE = "https://freewebnovel.com/novel/the-first-order"


def sample_registry():
    return {"version": 1, "novels": [
        {"title": "The World Online", "url": NOVELFULL,
         "downloads": [{"range": "all", "status": "complete",
                        "chapter_count": 1356,
                        "completed_at_utc": "2026-11-01T00:00:00Z",
                        "expires_at_utc": "2099-12-01T00:00:00Z",
                        "artifact_url": "https://github.com/example/artifact"}]},
        {"title": "Please, I Really Didn't Want To Fall in Love With My Master!",
         "url": COMMA, "downloads": []},
    ]}


CURATED = {"version": 1, "novels": [
    {"title": "The First Order", "url": FREE},
]}


class LibraryBulkTests(unittest.TestCase):
    def test_site_labels_for_historical_registry(self):
        self.assertEqual(website_name(NOVELFULL), "NovelFull")
        self.assertEqual(website_name("https://www.freewebnovel.com/novel/the-first-order"), "FreeWebNovel")
        self.assertEqual(website_name("https://example.org/book"), "example.org")

    def test_markdown_grouped_without_dropping_history(self):
        data = sample_registry()
        data["novels"].append({
            "title": "The First Order", "url": FREE,
            "downloads": [
                {"range": "1-2", "status": "complete", "chapter_count": 2,
                 "expires_at_utc": "2099-01-01T00:00:00Z",
                 "artifact_url": "https://github.com/example/free"},
                {"range": "1-5", "status": "complete", "chapter_count": 5,
                 "expires_at_utc": "2099-01-01T00:00:00Z",
                 "artifact_url": "https://github.com/example/free-second"},
            ],
        })
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_registry(data, root / "registry.json", root / "DOWNLOADED_NOVELS.md")
            rendered = (root / "DOWNLOADED_NOVELS.md").read_text(encoding="utf-8")
            self.assertIn("## NovelFull (2 novels)", rendered)
            self.assertIn("## FreeWebNovel (1 novels)", rendered)
            self.assertLess(rendered.index("## FreeWebNovel"), rendered.index("## NovelFull"))
            self.assertIn("[The World Online]("+NOVELFULL+")", rendered)
            self.assertIn("https://github.com/example/free-second", rendered)
            self.assertEqual(rendered.count("| Novel | Range | Chapters | Artifact | Expiry (UTC) |"), 2)
            self.assertEqual(read_registry(root / "registry.json"), data)
            self.assertNotIn('"website":', (root / "registry.json").read_text())

    def test_name_selection_and_grouped_matrices(self):
        plan = selection_plan(
            sample_registry(), CURATED, "The World Online; The First Order",
            "", "All", "1-2",
        )
        self.assertEqual(plan["selected_count"], 2)
        self.assertEqual([n["novel_url"] for n in plan["groups"]["NovelFull"]], [NOVELFULL])
        self.assertEqual([n["novel_url"] for n in plan["groups"]["FreeWebNovel"]], [FREE])
        self.assertEqual(plan["groups"]["NovelFull"][0]["chapter_range"], "1-2")

    def test_specific_website_selection(self):
        plan = selection_plan(sample_registry(), CURATED, "the first order",
                              "", "FreeWebNovel", "1-2")
        self.assertFalse(plan["groups"]["NovelFull"])
        self.assertEqual(len(plan["groups"]["FreeWebNovel"]), 1)
        with self.assertRaisesRegex(ValueError, "Unknown novel"):
            selection_plan(sample_registry(), CURATED, "The First Order", "", "NovelFull")

    def test_comma_in_exact_title_is_preserved(self):
        title = "Please, I Really Didn't Want To Fall in Love With My Master!"
        names = parse_names(title + "; The World Online",
                            [n["title"] for n in sample_registry()["novels"]])
        self.assertEqual(names, [title, "The World Online"])
        plan = selection_plan(sample_registry(), CURATED, title, "", "All")
        self.assertEqual(plan["groups"]["NovelFull"][0]["novel_url"], COMMA)

    def test_duplicate_names_and_urls_deduped(self):
        plan = selection_plan(sample_registry(), CURATED,
                              "The First Order, the first order", FREE, "All", "1-2")
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(len(plan["groups"]["FreeWebNovel"]), 1)

    def test_previous_download_skipped_unless_force(self):
        normal = selection_plan(sample_registry(), CURATED, "The World Online", "", "All")
        self.assertFalse(normal["groups"]["NovelFull"])
        self.assertEqual(len(normal["skipped"]), 1)
        forced = selection_plan(sample_registry(), CURATED, "The World Online", "", "All",
                                force=True)
        self.assertEqual(len(forced["groups"]["NovelFull"]), 1)
        self.assertTrue(forced["groups"]["NovelFull"][0]["force"])

    def test_unknown_ambiguous_and_wrong_site_fail_without_guessing(self):
        with self.assertRaisesRegex(ValueError, "Unknown novel"):
            selection_plan(sample_registry(), CURATED, "Fantasy Book Not Saved", "", "All")
        with self.assertRaisesRegex(ValueError, "filter is NovelFull"):
            selection_plan(sample_registry(), CURATED, "", FREE, "NovelFull")
        doubled = {"version": 1, "novels": [
            *CURATED["novels"],
            {"title": "The World Online", "url": FREE},
        ]}
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            selection_plan(sample_registry(), doubled, "The World Online", "", "All")

    def test_direct_new_url_and_websites_rejected(self):
        plan = selection_plan(sample_registry(), CURATED, "", FREE, "All", "1-2")
        self.assertEqual(plan["groups"]["FreeWebNovel"][0]["novel_url"], FREE)
        for bad in (
            "https://freewebnovel.com/home",
            "https://novelfull.com/",
            "https://example.com/novel",
            "https://freewebnovel.com.evil.test/novel/the-first-order",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                selection_plan(sample_registry(), CURATED, "", bad, "All", "1-2")

    def test_empty_and_bad_ranges_fail(self):
        with self.assertRaisesRegex(ValueError, "Choose at least"):
            selection_plan(sample_registry(), CURATED, "", "", "All")
        with self.assertRaisesRegex(ValueError, "range"):
            selection_plan(sample_registry(), CURATED, "The First Order", "", "All", "3-1")

    def test_cli_outputs_matrices_and_no_live_requests(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = root / "downloads.json"
            cat = root / "sources.json"
            out = root / "outputs.txt"
            summary = root / "summary.md"
            reg.write_text(json.dumps(sample_registry()), encoding="utf-8")
            cat.write_text(json.dumps(CURATED), encoding="utf-8")
            with patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary),
            }):
                self.assertEqual(main([
                    "plan", "--registry", str(reg), "--catalogue", str(cat),
                    "--names", "The World Online; The First Order",
                    "--chapter-range", "1-2", "--plan-file", str(root / "plan.json"),
                ]), 0)
            pairs = dict(line.split("=", 1) for line in out.read_text().splitlines())
            self.assertEqual(pairs["has_novelfull"], "true")
            self.assertEqual(pairs["has_freewebnovel"], "true")
            self.assertEqual(
                json.loads(pairs["novelfull_matrix"])["include"][0]["novel_url"], NOVELFULL
            )
            self.assertIn("### FreeWebNovel", summary.read_text())

    def test_real_registry_titles_listed_without_network(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "registry.json"
            catalogue = root / "novel_sources.json"
            registry.write_text(json.dumps(sample_registry()), encoding="utf-8")
            catalogue.write_text(json.dumps(CURATED), encoding="utf-8")
            self.assertEqual(
                main(["list", "--registry", str(registry),
                      "--catalogue", str(catalogue)]), 0,
            )


if __name__ == "__main__":
    unittest.main()
