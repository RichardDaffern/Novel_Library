#!/usr/bin/env python3
"""Download ONLY novel covers, using DOWNLOADED_NOVELS.md as the source list.

Never fetch chapters, download EPUBs, or modify existing novel ZIP files.
Output: Downloaded_Covers/<website>/<novel-title>-<url-hash>.jpg/png.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time

from novel_downloader import slugify
from tools.download_registry import website_name
from tools.novel_covers import (
    CoverError, download_site_cover, fetch_html, fetch_image,
    validate_book_url, validate_image,
)

DEFAULT_MARKDOWN = Path("DOWNLOADED_NOVELS.md")
DEFAULT_OUTPUT = Path("Downloaded_Covers")
# The registry includes multiple chapter ranges per book. Select each book
# once, using its source URL rather than an artifact URL.
BOOK_ROW = re.compile(r"^\s*\|\s*\[([^\]]+)\]\((https://[^)]+)\)\s*\|")
WEBSITES = ("All", "NovelFull", "FreeWebNovel")


def read_markdown_novels(source: Path) -> list[dict]:
    """Use the actual Markdown registry, not its JSON counterpart."""
    if not source.is_file():
        raise ValueError(f"Downloaded novel index not found: {source}")
    novels = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        match = BOOK_ROW.match(line)
        if not match:
            continue
        title, raw_url = match.groups()
        try:
            url = validate_book_url(raw_url)
        except CoverError as exc:
            raise ValueError(f"Unsupported book URL in {source}: {raw_url}: {exc}") from exc
        if not title.strip():
            raise ValueError("An indexed novel has no title")
        if url not in novels:
            novels[url] = {
                "title": title.strip(),
                "url": url,
                "website": website_name(url),
            }
    if not novels:
        raise ValueError(f"No linked novels found in {source}")
    return sorted(novels.values(), key=lambda item: (
        item["website"].casefold(), item["title"].casefold(), item["url"]
    ))


def cover_basename(record: dict) -> str:
    # Hash the source URL to prevent identically named books from colliding.
    suffix = sha256(record["url"].encode("utf-8")).hexdigest()[:8]
    return slugify(record["title"])[:85] + "-" + suffix


def select_novels(items: list[dict], website: str, limit: int) -> list[dict]:
    if website not in WEBSITES:
        raise ValueError("Unsupported website selection")
    if limit < 0:
        raise ValueError("Limit must be nonnegative")
    selected = [item for item in items if website == "All"
                or item["website"] == website]
    return selected[:limit] if limit else selected


def download_covers(records: list[dict], out: Path, *, dry_run=False,
                    confirm_rights=False, force=False, delay=1.0,
                    page_fetcher=fetch_html, image_fetcher=fetch_image,
                    sleeper=time.sleep) -> dict:
    if not dry_run and not confirm_rights:
        raise ValueError("--confirm-rights is required to request images")
    if delay < 0:
        raise ValueError("Delay must be nonnegative")
    results = []
    for index, item in enumerate(records):
        folder = out / item["website"]
        stem = cover_basename(item)
        result = dict(item)
        result["novel_id"] = sha256(item["url"].encode("utf-8")).hexdigest()[:8]
        result["source_url"] = item["url"]
        result["status"] = ""
        if dry_run:
            result["status"] = "planned"
            results.append(result)
            print(f"[plan] {item['website']}: {item['title']}")
            continue
        candidates = [folder / (stem + ext) for ext in (".jpg", ".png")]
        existing = [p for p in candidates if p.exists()]
        if existing and not force:
            try:
                for path in existing:
                    _, extension = validate_image(path.read_bytes())
                    if path.suffix.lower() != extension:
                        raise CoverError("Existing cover extension does not match content")
                result.update(
                    status="skipped", path=str(existing[0]),
                    cover_file=f"{item['website']}/{existing[0].name}",
                )
                print(f"[skip] {item['title']}")
            except (CoverError, OSError) as exc:
                result.update(status="failed", error=f"Existing image requires --force: {exc}")
                print(f"[failed] {item['title']}: {result['error']}", file=sys.stderr)
            results.append(result)
            continue
        try:
            if index:
                sleeper(delay)
            data, extension, cover_url = download_site_cover(
                item["url"], html_fetcher=page_fetcher,
                image_fetcher=image_fetcher,
            )
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / (stem + extension)
            # Stage a validated image in the destination directory before
            # replacing any existing file. A network/write failure must not
            # damage an existing cover.
            import tempfile
            with tempfile.NamedTemporaryFile(
                prefix=".cover-", suffix=extension, dir=folder, delete=False
            ) as tmp:
                staged = Path(tmp.name)
            try:
                staged.write_bytes(data)
                _, validated_extension = validate_image(staged.read_bytes())
                if validated_extension != extension:
                    raise CoverError("Staged cover failed format verification")
                staged.replace(destination)
                for old in candidates:
                    if old != destination:
                        old.unlink(missing_ok=True)
            finally:
                staged.unlink(missing_ok=True)
            result.update(
                status="downloaded", path=str(destination),
                cover_file=f"{item['website']}/{destination.name}",
                cover_source_url=cover_url,
            )
            print(f"[saved] {item['website']}: {item['title']} -> {destination}")
        except (CoverError, OSError, ValueError) as exc:
            result.update(status="failed", error=str(exc))
            print(f"[failed] {item['title']}: {exc}", file=sys.stderr)
        results.append(result)
    summary = {
        "total": len(results),
        "downloaded": sum(x["status"] == "downloaded" for x in results),
        "skipped": sum(x["status"] == "skipped" for x in results),
        "failed": sum(x["status"] == "failed" for x in results),
        "results": results,
    }
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
        (out / "covers_manifest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_MARKDOWN,
                        help="Markdown index listing completed novel downloads")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--website", choices=WEBSITES, default="All")
    parser.add_argument("--limit", type=int, default=0, help="0 downloads every indexed cover")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Replace previously downloaded covers")
    parser.add_argument("--confirm-rights", action="store_true",
                        help="Confirm permission to save these cover images")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Seconds between book-page requests (default 1)")
    args = parser.parse_args(argv)
    try:
        records = select_novels(
            read_markdown_novels(args.index), args.website, args.limit,
        )
        summary = download_covers(
            records, args.output_dir, dry_run=args.dry_run,
            confirm_rights=args.confirm_rights, force=args.force,
            delay=args.delay,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Covers: {summary['downloaded']} downloaded, "
          f"{summary['skipped']} skipped, {summary['failed']} failed "
          f"({summary['total']} selected)")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
