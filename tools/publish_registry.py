#!/usr/bin/env python3
"""Publish completed novel metadata through an optimistic, retryable GitHub PR.

Download jobs are deliberately not globally serialised. Each attempt rebuilds
the registry from the *latest* main branch before pushing the PR, so competing
novel completions cannot silently overwrite each other's metadata.
Only the registry JSON and Markdown are committed, never EPUB or chapter text.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from tools.chunked_download import identity
from tools.download_registry import (
    canonical_url, normalise_range, read_registry, record_download, write_registry,
)


class RegistryPublishError(RuntimeError):
    """An automatic registry PR could not be created or merged."""


def run_command(*command: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=90)
    if check and result.returncode:
        raise RegistryPublishError(
            f"Command {' '.join(command[:3])!r} failed: {(result.stderr or result.stdout).strip()}"
        )
    return result


def append_summary(message: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")


def branch_for(url: str, run_id: str) -> str:
    return f"registry/download-{run_id}-{identity(canonical_url(url))}"


def register_on_current_base(
    url: str, chapter_range: str, downloads_dir: Path, run_id: str,
    artifact_id: str, artifact_url: str,
    registry_path: Path = Path("downloaded_novels.json"),
    markdown_path: Path = Path("DOWNLOADED_NOVELS.md"),
) -> bool:
    """Rebuild one record on whatever revision of main has just been checked out.

    Returns False if this exact run's artifact is already registered.
    """
    registry = read_registry(registry_path)
    url = canonical_url(url)
    for novel in registry["novels"]:
        if canonical_url(novel["url"]) == url:
            if any(str(entry.get("run_id")) == run_id
                   and str(entry.get("artifact_id")) == artifact_id
                   for entry in novel.get("downloads", [])):
                return False
    record_download(
        registry, url, chapter_range, downloads_dir, run_id, artifact_url, artifact_id
    )
    write_registry(registry, registry_path, markdown_path)
    return True


def publish(
    url: str, chapter_range: str, downloads_dir: Path, run_id: str,
    artifact_id: str, artifact_url: str, attempts: int = 6,
    delay=time.sleep,
) -> str:
    if attempts < 1 or attempts > 20:
        raise ValueError("Retry attempts must be between 1 and 20")
    url = canonical_url(url)
    chapter_range = normalise_range(chapter_range)
    if not run_id.isdigit() or not artifact_id.isdigit():
        raise ValueError("The GitHub run ID and artifact ID must be numeric")
    if not artifact_url.startswith("https://github.com/"):
        raise ValueError("Expected a GitHub Actions artifact URL")

    branch = branch_for(url, run_id)
    run_command("git", "config", "user.name", "github-actions[bot]")
    run_command("git", "config", "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com")
    pr_url = ""

    for attempt in range(1, attempts + 1):
        print(f"Registry PR publish attempt {attempt}/{attempts} for {url}", flush=True)
        run_command("git", "fetch", "origin", "main")
        run_command("git", "switch", "-C", branch, "origin/main")
        updated = register_on_current_base(
            url, chapter_range, downloads_dir, run_id, artifact_id, artifact_url
        )
        if not updated:
            print(f"Run {run_id} is already recorded on main.", flush=True)
            return pr_url or "Already merged into main"
        run_command("git", "add", "downloaded_novels.json", "DOWNLOADED_NOVELS.md")
        run_command("git", "commit", "-m", f"Track completed novel download (run {run_id})")
        run_command("git", "push", "--force-with-lease", "--set-upstream", "origin", branch)

        if not pr_url:
            created = run_command(
                "gh", "pr", "create", "--base", "main", "--head", branch,
                "--title", f"Track completed novel download #{run_id}",
                "--body", (
                    "Verified metadata-only registry update. The final EPUB and TXT "
                    "chapters remain in the Actions artifact, not the Git repository."
                ),
                check=False,
            )
            if created.returncode:
                repo = os.environ.get("GITHUB_REPOSITORY", "RichardDaffern/Novel_Library")
                comparison = f"https://github.com/{repo}/compare/main...{branch}?expand=1"
                append_summary(
                    "## Automatic registry PR could not be created\n"
                    f"Your completed novel artifact is safe: {artifact_url}\n"
                    f"Manual registry PR link: {comparison}\n"
                    "Confirm that GitHub Actions may create and approve pull requests."
                )
                raise RegistryPublishError(
                    f"GitHub rejected PR creation: {created.stderr.strip() or created.stdout.strip()}. "
                    f"The metadata branch is preserved: {comparison}"
                )
            pr_url = created.stdout.strip()
            print(f"Opened registry PR: {pr_url}", flush=True)
            append_summary(f"Registry PR: {pr_url}")

        merged = run_command(
            "gh", "pr", "merge", pr_url, "--squash", "--delete-branch",
            check=False,
        )
        if merged.returncode == 0:
            print(f"Registry PR merged into main: {pr_url}", flush=True)
            append_summary(f"Registry merged into main: {pr_url}\nArtifact: {artifact_url}")
            return pr_url

        # The PR can become out of date while another novel's PR merges.
        # Rebuild on the latest main branch rather than dropping either novel.
        state = run_command("gh", "pr", "view", pr_url, "--json", "state", check=False)
        if state.returncode == 0:
            try:
                if json.loads(state.stdout).get("state") == "MERGED":
                    append_summary(f"Registry PR confirmed merged: {pr_url}")
                    return pr_url
            except ValueError:
                pass

        print(f"Merge attempt {attempt} did not complete: {(merged.stderr or merged.stdout).strip()}",
              flush=True)
        if attempt < attempts:
            delay(min(3 * attempt, 12))

    append_summary(
        "## Registry PR needs attention\n"
        f"Final novel artifact: {artifact_url}\n"
        f"Open registry PR (not merged): {pr_url}\n"
        "Automatic merge attempts were exhausted. Check branch policies and PR checks."
    )
    raise RegistryPublishError(
        f"Unable to merge registry PR after {attempts} attempts: {pr_url}. "
        "Artifact remains available."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--chapter-range", default="")
    parser.add_argument("--downloads-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--attempts", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        publish(
            args.url, args.chapter_range, args.downloads_dir,
            args.run_id, args.artifact_id, args.artifact_url, args.attempts,
        )
    except (ValueError, OSError, subprocess.SubprocessError, RegistryPublishError) as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
