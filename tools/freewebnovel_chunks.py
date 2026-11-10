#!/usr/bin/env python3
"""FreeWebNovel's site-specific orchestration over shared verified batch APIs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from tools import chunked_download as batches
from tools.bulk_download import create_plan, parse_novel_urls
from tools.download_registry import read_registry
from tools.freewebnovel_downloader import book_details
from tools.freewebnovel_probe import fetch_public_html, validate_book_url


def _output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def plan_download(url: str, chapter_range: str, chunk_size: int, plan_file: Path,
                  *, fetcher=fetch_public_html):
    url = validate_book_url(url)
    if chunk_size < 1 or chunk_size > 100:
        raise ValueError("FreeWebNovel chunk size must be 1-100")
    details = book_details(fetcher(url), url)
    plan = batches.chapter_plan(url, details["numChapters"], chapter_range, chunk_size)
    # Keep the source-site request rate conservative. Batches each download
    # one chapter per second and at most two batches are active concurrently.
    plan["parallelism"] = min(2, plan["parallelism"])
    plan_file.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    _output("matrix", json.dumps({"include": plan["pieces"]}, separators=(",", ":")))
    for field in ("key", "first", "last", "parallelism"):
        _output(field, str(plan[field]))
    print(f"FreeWebNovel: {details['title']}, published up to Chapter {details['numChapters']}")
    print(f"Planned {len(plan['pieces'])} batches, Chapters {plan['first']}-{plan['last']}, "
          f"max {plan['parallelism']} parallel batches")
    return plan


def fetch_batch(url: str, key: str, first: int, last: int,
                folder: Path, scratch: Path, *, timeout_minutes=65,
                force=False, runner=subprocess.run):
    url = validate_book_url(url)
    if (key != batches.identity(url) or first < 1 or last < first
            or last - first + 1 > 100):
        raise ValueError("Invalid FreeWebNovel chapter range/key")
    if not force and batches.reuse_complete_piece(folder, url, key, first, last):
        return
    command = [
        sys.executable, "-u", "-m", "tools.freewebnovel_downloader",
        url, "--chapter-range", f"{first}-{last}",
        "--output-dir", str(scratch), "--confirm-rights",
    ]
    runner(command, check=True, timeout=timeout_minutes * 60)
    metadata_files = list(scratch.rglob("metadata.json"))
    if len(metadata_files) != 1:
        raise ValueError(f"Expected one chapter-range directory, found {len(metadata_files)}")
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copytree(metadata_files[0].parent, folder / "book", dirs_exist_ok=True)
    (folder / "part.json").write_text(json.dumps({
        "version": 1, "url": url, "key": key,
        "start": first, "end": last,
    }, indent=2) + "\n", encoding="utf-8")
    batches.validate_piece(folder, url, key, first, last)
    print(f"VERIFIED FreeWebNovel chapters {first}-{last}", flush=True)


def plan_bulk(raw_urls: str, chapter_range: str, force: bool,
              *, registry=Path("downloaded_novels.json")):
    urls = [validate_book_url(url) for url in parse_novel_urls(raw_urls)]
    download_plan = create_plan(read_registry(registry), " ".join(urls),
                                chapter_range, force)
    matrix = {
        "include": [
            {
                "novel_url": entry["url"],
                "chapter_range": "" if entry["range"] == "all" else entry["range"],
                "force": download_plan["force"],
            }
            for entry in download_plan["planned"]
        ],
    }
    _output("has_work", "true" if matrix["include"] else "false")
    _output("matrix", json.dumps(matrix, separators=(",", ":")))
    print(f"FreeWebNovel bulk: {len(matrix['include'])} to download, "
          f"{len(download_plan['skipped'])} already available")
    return download_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "fetch", "assemble", "bulk-plan"])
    parser.add_argument("--url", default="")
    parser.add_argument("--urls", default="")
    parser.add_argument("--chapter-range", default="")
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--key", default="")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout-minutes", type=int, default=65)
    parser.add_argument("--plan-file", type=Path, default=Path("chapter_plan.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("chapter_batch"))
    parser.add_argument("--scratch-dir", type=Path, default=Path("scratch"))
    parser.add_argument("--chunks-dir", type=Path, default=Path("completed_batches"))
    args = parser.parse_args(argv)
    if args.action == "bulk-plan":
        plan_bulk(args.urls, args.chapter_range, args.force)
        return 0
    url = validate_book_url(args.url)
    if args.action == "plan":
        plan_download(url, args.chapter_range, args.chunk_size, args.plan_file)
        return 0
    if args.action == "fetch":
        fetch_batch(url, args.key, args.start, args.end,
                    args.output_dir, args.scratch_dir,
                    timeout_minutes=args.timeout_minutes, force=args.force)
        return 0
    if args.action == "assemble":
        plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
        if plan.get("url") != url:
            raise ValueError("Cannot assemble batches from a different FreeWebNovel URL")
        batches.assemble(plan, args.chunks_dir, args.output_dir)
        return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"FreeWebNovel workflow stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
