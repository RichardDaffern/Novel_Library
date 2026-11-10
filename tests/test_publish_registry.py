"""Offline tests for concurrent download registry publication."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest
from unittest.mock import patch

from tools.publish_registry import (
    RegistryPublishError, branch_for, publish, register_on_current_base,
)

URL_A = "https://example.org/story-a"
URL_B = "https://example.org/story-b"
ARTIFACT = "https://github.com/RichardDaffern/Novel_Library/actions/runs/123/artifacts/456"


def mock_book(root: Path, url: str, title: str) -> Path:
    folder = root / title.replace(" ", "-")
    folder.mkdir(parents=True)
    (folder / "source.epub").write_bytes(b"synthetic epub")
    (folder / "chapter_0001.txt").write_text("This is an offline synthetic chapter.", encoding="utf-8")
    (folder / "metadata.json").write_text(json.dumps({
        "title": title, "author": "Test", "source_url": url, "chapter_count": 1,
    }), encoding="utf-8")
    (folder / "chapters.json").write_text(json.dumps([
        {"position": 1, "file": "chapter_0001.txt"},
    ]), encoding="utf-8")
    return folder


class PublishRegistryTests(unittest.TestCase):
    def test_concurrent_novel_branches_have_distinct_names(self):
        self.assertNotEqual(branch_for(URL_A, "123"), branch_for(URL_B, "123"))
        self.assertNotEqual(branch_for(URL_A, "123"), branch_for(URL_A, "124"))

    def test_regenerating_registry_from_latest_base_preserves_both_novels(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "downloaded_novels.json"
            markdown = root / "DOWNLOADED_NOVELS.md"
            novel_a = mock_book(root / "downloads-a", URL_A, "Story A")
            novel_b = mock_book(root / "downloads-b", URL_B, "Story B")
            a = register_on_current_base(
                URL_A, "1-1", novel_a, "123", "456", ARTIFACT,
                registry, markdown,
            )
            b = register_on_current_base(
                URL_B, "1-1", novel_b, "124", "457", ARTIFACT,
                registry, markdown,
            )
            self.assertTrue(a)
            self.assertTrue(b)
            data = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual({novel["url"] for novel in data["novels"]}, {URL_A, URL_B})
            self.assertIn("[Story A]", markdown.read_text(encoding="utf-8"))
            self.assertIn("[Story B]", markdown.read_text(encoding="utf-8"))
            self.assertFalse(register_on_current_base(
                URL_A, "1-1", novel_a, "123", "456", ARTIFACT,
                registry, markdown,
            ))
            self.assertEqual(len(json.loads(registry.read_text())["novels"]), 2)

    def test_outdated_pr_rebuilds_from_fresh_main_and_retries_merge(self):
        calls = []
        merges = [1, 0]

        def simulated(*args, check=True):
            calls.append(args)
            if args[:3] == ("gh", "pr", "create"):
                return subprocess.CompletedProcess(args, 0, "https://github.com/RichardDaffern/Novel_Library/pull/10\n", "")
            if args[:3] == ("gh", "pr", "merge"):
                failure = merges.pop(0)
                return subprocess.CompletedProcess(args, failure, "", "Base branch was updated" if failure else "")
            if args[:3] == ("gh", "pr", "view"):
                return subprocess.CompletedProcess(args, 0, '{"state":"OPEN"}', "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch("tools.publish_registry.run_command", side_effect=simulated), \
                patch("tools.publish_registry.register_on_current_base", return_value=True) as register:
            url = publish(URL_A, "", Path("downloads"), "123", "456", ARTIFACT,
                          attempts=3, delay=lambda _: None)

        self.assertTrue(url.endswith("/10"))
        self.assertEqual(len([c for c in calls if c[:3] == ("git", "fetch", "origin")]), 2)
        self.assertEqual(len([c for c in calls if c[:3] == ("gh", "pr", "merge")]), 2)
        self.assertEqual(len([c for c in calls if c[:3] == ("gh", "pr", "create")]), 1)
        self.assertEqual(register.call_count, 2)
        self.assertEqual(len([c for c in calls if c[:2] == ("git", "push")]), 2)

    def test_github_pr_permission_rejection_preserves_pushed_branch(self):
        calls = []

        def simulated(*args, check=True):
            calls.append(args)
            if args[:3] == ("gh", "pr", "create"):
                return subprocess.CompletedProcess(args, 1, "", "PR creation not permitted")
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch("tools.publish_registry.run_command", side_effect=simulated), \
                patch("tools.publish_registry.register_on_current_base", return_value=True):
            with self.assertRaisesRegex(RegistryPublishError, "not permitted"):
                publish(URL_A, "", Path("downloads"), "123", "456", ARTIFACT,
                        delay=lambda _: None)
        self.assertTrue(any(c[:2] == ("git", "push") for c in calls))

    def test_workflow_uses_dynamic_parallelism_and_safe_pr_merger(self):
        workflow = Path(".github/workflows/download-novel.yml").read_text(encoding="utf-8")
        bulk = Path(".github/workflows/library-bulk-download.yml").read_text(encoding="utf-8")
        self.assertIn("max-parallel: ${{ fromJSON(needs.prepare.outputs.parallelism) }}", workflow)
        self.assertIn("parallelism: ${{ steps.make_plan.outputs.parallelism }}", workflow)
        self.assertIn("group: novel-download-${{ inputs.novel_url }}", workflow)
        self.assertNotIn("group: novel-library-registry", workflow)
        self.assertIn("python -u -m tools.publish_registry", workflow)
        self.assertIn("max-parallel: 3", bulk)
        self.assertIn("max-parallel: 2", bulk)
        self.assertIn("uses: ./.github/workflows/download-novel.yml", bulk)
        self.assertIn("uses: ./.github/workflows/freewebnovel-download.yml", bulk)


if __name__ == "__main__":
    unittest.main()
