#!/usr/bin/env python3
"""Plan and run multiple authorised novel downloads in one Actions job.

Downloaded chapters and EPUBs are uploaded as an artifact, never committed to Git.
Only completed, validated downloads are recorded in the metadata registry.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from tools.download_registry import (
    already_available, canonical_url, normalise_range,
    read_registry, record_download, write_registry,
)

MAX_NOVELS = 10


def parse_novel_urls(raw: str, limit: int = MAX_NOVELS) -> list[str]:
    """Parse whitespace/comma/semicolon-delimited HTTPS links and deduplicate."""
    items = re.split(r"[\s,;]+", raw.strip())
    urls: list[str] = []
    seen: set[str] = set()
    for token in items:
        if not token:
            continue
        url = canonical_url(token)
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) > limit:
            raise ValueError(f"Maximum {limit} distinct novel URLs per batch")
    if not urls:
        raise ValueError("Enter at least one novel URL")
    return urls


def storage_key(url: str, chapter_range: str) -> str:
    """Avoid output collisions between sites, titles, and ranges."""
    return hashlib.sha256((url + "\n" + chapter_range).encode("utf-8")).hexdigest()[:16]


def create_plan(registry: dict, raw_urls: str, chapter_range: str = "",
                force: bool = False) -> dict:
    urls = parse_novel_urls(raw_urls)
    chapter_range = normalise_range(chapter_range)
    planned: list[dict] = []
    skipped: list[dict] = []
    for url in urls:
        entry = {"url": url, "range": chapter_range, "folder": storage_key(url, chapter_range)}
        if not force and already_available(registry, url, chapter_range):
            skipped.append({**entry, "reason": "Already downloaded; artifact still available"})
        else:
            planned.append(entry)
    return {"version": 1, "planned": planned, "skipped": skipped, "force": bool(force)}


def _save_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{key}={value}\n")


def run_batch(plan: dict, base_dir: Path, runner: str = sys.executable,
              max_total_minutes: int = 305, per_novel_minutes: int = 170,
              clock=time.monotonic, invoke=subprocess.run) -> dict:
    """Continue with remaining novels if an individual downloader fails."""
    result = {"version": 1, "completed": [], "failed": [], "skipped": plan["skipped"]}
    start = clock()
    base_dir.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(plan["planned"], 1):
        remaining = (max_total_minutes * 60 - (clock() - start)) // 60
        if remaining < 2:
            result["failed"].append({**item, "error": "Batch time budget exhausted"})
            print(f"NOT STARTED {index}: batch time budget exhausted", flush=True)
            continue
        max_minutes = max(1, min(per_novel_minutes, int(remaining)))
        folder = base_dir / item["folder"]
        command = [
            runner, "-u", "novel_downloader.py", item["url"],
            "--confirm-rights", "--output-dir", str(folder),
            "--timeout-minutes", str(max_minutes),
        ]
        if item["range"] != "all":
            command.extend(["--chapter-range", item["range"]])
        print(f"\n=== Novel {index}/{len(plan['planned'])}: {item['url']} [range {item['range']}] ===", flush=True)
        try:
            outcome = invoke(command, check=False, timeout=max_minutes * 60 + 25)
            ok = outcome.returncode == 0
            error = f"Downloader exited with code {outcome.returncode}" if not ok else ""
        except (subprocess.TimeoutExpired, OSError) as exc:
            ok, error = False, f"{type(exc).__name__}: {exc}"
        if ok:
            print(f"COMPLETED: {item['url']}", flush=True)
            result["completed"].append(item)
        else:
            print(f"FAILED: {item['url']}: {error}", flush=True)
            result["failed"].append({**item, "error": error})
    return result


def validate_and_record(registry: dict, results: dict, downloads_dir: Path,
                        run_id: str, artifact_id: str, artifact_url: str) -> int:
    if not artifact_id or not artifact_url:
        raise ValueError("No GitHub Actions artifact was uploaded")
    count = 0
    for entry in results["completed"]:
        record_download(
            registry, entry["url"], entry["range"],
            downloads_dir / entry["folder"],
            run_id, artifact_url, artifact_id,
        )
        count += 1
    return count


def summary(results: dict) -> str:
    lines = [
        "## Bulk novel download result", "",
        f"**Completed:** {len(results.get('completed', []))}  |  "
        f"**Skipped:** {len(results.get('skipped', []))}  |  "
        f"**Failed:** {len(results.get('failed', []))}", "",
        "| Novel URL | Result | Range |",
        "|---|---|---|",
    ]
    for kind, label in (("completed", "Completed"), ("skipped", "Already available"), ("failed", "Failed")):
        for item in results.get(kind, []):
            lines.append(f"| {item['url']} | {label} | {item['range']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "download", "record", "report"])
    parser.add_argument("--urls", default="", help="URLs separated by commas, spaces, or newlines")
    parser.add_argument("--chapter-range", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--registry", type=Path, default=Path("downloaded_novels.json"))
    parser.add_argument("--markdown", type=Path, default=Path("DOWNLOADED_NOVELS.md"))
    parser.add_argument("--plan-file", type=Path, default=Path("batch_plan.json"))
    parser.add_argument("--results-file", type=Path, default=Path("batch_results.json"))
    parser.add_argument("--downloads-dir", type=Path, default=Path("downloads"))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--artifact-id", default="")
    parser.add_argument("--artifact-url", default="")
    parser.add_argument("--budget-minutes", type=int, default=305)
    args = parser.parse_args(argv)

    if args.action == "plan":
        plan = create_plan(read_registry(args.registry), args.urls, args.chapter_range, args.force)
        _save_json(args.plan_file, plan)
        _append_output("has_work", "true" if plan["planned"] else "false")
        print(f"Batch: {len(plan['planned'])} to download, {len(plan['skipped'])} already available", flush=True)
        for item in plan["skipped"]:
            print(f"SKIPPED (already downloaded): {item['url']} [{item['range']}]", flush=True)
        if not plan["planned"]:
            _save_json(args.results_file, {"version": 1, "completed": [], "failed": [], "skipped": plan["skipped"]})
        return 0

    if args.action == "download":
        plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
        if args.budget_minutes < 1:
            parser.error("--budget-minutes must be positive")
        try:
            result = run_batch(plan, args.downloads_dir, max_total_minutes=args.budget_minutes)
        finally:
            # The individual calls continue on errors; a completed run always
            # writes its result manifest before artifact upload.
            pass
        _save_json(args.results_file, result)
        print(summary(result), flush=True)
        return 0

    if args.action == "record":
        if not all((args.run_id, args.artifact_id, args.artifact_url)):
            parser.error("record requires --run-id, --artifact-id, and --artifact-url")
        result = json.loads(args.results_file.read_text(encoding="utf-8"))
        registry = read_registry(args.registry)
        count = validate_and_record(
            registry, result, args.downloads_dir,
            args.run_id, args.artifact_id, args.artifact_url,
        )
        if count:
            write_registry(registry, args.registry, args.markdown)
        print(f"Recorded {count} completed novel(s); incomplete jobs were not registered.", flush=True)
        return 0

    if args.action == "report":
        if not args.results_file.is_file():
            print("No batch result manifest exists.")
            return 1
        result = json.loads(args.results_file.read_text(encoding="utf-8"))
        report = summary(result)
        print(report, flush=True)
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(report)
        return 1 if result["failed"] else 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
