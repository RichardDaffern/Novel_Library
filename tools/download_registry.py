#!/usr/bin/env python3
"""Track completed novel downloads without committing novel text or EPUBs.

The registry is metadata only. An expired GitHub Actions artifact does not
count as an available download, even though its history remains recorded.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit


DEFAULT_REGISTRY = {"version": 1, "novels": []}
RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def canonical_url(value: str) -> str:
    value = value.strip()
    p = urlsplit(value)
    if p.scheme.lower() != "https" or not p.hostname or p.username or p.password:
        raise ValueError("A valid HTTPS novel URL is required")
    host = p.hostname.lower()
    if p.port not in (None, 443):
        host += f":{p.port}"
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, p.query, ""))


def normalise_range(value: str | None) -> str:
    if not value or not value.strip():
        return "all"
    m = RANGE_RE.fullmatch(value.strip())
    if not m:
        raise ValueError("Chapter range must be START-END, for example 1-30")
    start, end = map(int, m.groups())
    if start < 1 or end < start:
        raise ValueError("Chapter range must start at 1 and end at or after the start")
    return f"{start}-{end}"


def read_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "novels": []}
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("version") != 1 or not isinstance(result.get("novels"), list):
        raise ValueError("Invalid downloaded-novels registry format")
    return result


def expiry(record: dict) -> datetime | None:
    raw = record.get("expires_at_utc")
    if not raw:
        return None
    try:
        date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return date.astimezone(timezone.utc) if date.tzinfo else None


def available_ranges(novel: dict, now: datetime) -> list[str]:
    return [
        rec["range"]
        for rec in novel.get("downloads", [])
        if rec.get("status") == "complete"
        and expiry(rec) is not None
        and expiry(rec) > now
        and rec.get("range")
    ]


def already_available(registry: dict, url: str, chapter_range: str = "all",
                      now: datetime | None = None) -> bool:
    url = canonical_url(url)
    chapter_range = normalise_range(chapter_range if chapter_range != "all" else "")
    now = now or datetime.now(timezone.utc)
    novel = next((book for book in registry["novels"] if canonical_url(book["url"]) == url), None)
    if not novel:
        return False
    ranges = available_ranges(novel, now)
    if "all" in ranges:
        return True
    if chapter_range == "all":
        return False
    start, end = map(int, chapter_range.split("-"))
    segments = sorted(
        (tuple(map(int, item.split("-"))) for item in ranges if item != "all"),
        key=lambda x: x[0],
    )
    cursor = start
    for lower, upper in segments:
        if lower <= cursor <= upper:
            cursor = upper + 1
        if cursor > end:
            return True
    return False


def _text(value: str) -> str:
    return str(value or "").replace("|", r"\|").replace("\n", " ").strip()


SITE_LABELS = {
    "novelfull.com": "NovelFull",
    "freewebnovel.com": "FreeWebNovel",
    "scribblehub.com": "Scribble Hub",
}


def website_name(url: str) -> str:
    """Human-readable source, inferred for old records without schema migration."""
    host = (urlsplit(canonical_url(url)).hostname or "").lower()
    host = host.removeprefix("www.")
    return SITE_LABELS.get(host, host)


def write_registry(registry: dict, json_path: Path, md_path: Path) -> None:
    # Preserve the established version-1 JSON structure and every historical
    # record/artifact link. Website grouping is a presentation concern only.
    registry["novels"].sort(key=lambda n: n["url"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    groups: dict[str, list[dict]] = {}
    for novel in registry["novels"]:
        groups.setdefault(website_name(novel["url"]), []).append(novel)
    lines = [
        "# Downloaded novels",
        "",
        "This is an index of **completed** downloads, not a copy of the novels.",
        "Actual text/EPUB files are in temporary GitHub Actions artifacts, **not the Git repository**.",
        "Expired artifacts cannot be retrieved; such entries remain as history but will not block a new download.",
        "",
    ]
    if not groups:
        lines.append("No completed downloads yet.")
    for website in sorted(groups, key=str.casefold):
        novels = sorted(
            groups[website], key=lambda n: ((n.get("title") or n["url"]).casefold(), n["url"])
        )
        lines.extend([
            f"## {website} ({len(novels)} novels)",
            "",
            "| Novel | Range | Chapters | Artifact | Expiry (UTC) |",
            "|---|---|---:|---|---|",
        ])
        for novel in novels:
            for item in sorted(novel.get("downloads", []), key=lambda v: v.get("completed_at_utc", "")):
                link = item.get("artifact_url") or item.get("run_url") or ""
                status = "Available" if (expiry(item) or now) > now and expiry(item) else "Expired"
                artifact = f"[{status}]({link})" if link else status
                lines.append(
                    f"| [{_text(novel.get('title') or novel['url'])}]({novel['url']}) | "
                    f"{_text(item.get('range'))} | "
                    f"{item.get('chapter_count', 0)} | {artifact} | {_text(item.get('expires_at_utc'))} |"
                )
        lines.append("")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def record_download(registry: dict, url: str, chapter_range: str, downloads_dir: Path,
                    run_id: str, artifact_url: str, artifact_id: str,
                    retention_days: int = 7,
                    now: datetime | None = None) -> dict:
    url = canonical_url(url)
    chapter_range = normalise_range(chapter_range if chapter_range != "all" else "")
    files = list(downloads_dir.rglob("metadata.json"))
    if len(files) != 1:
        raise ValueError(f"Expected exactly one metadata.json under {downloads_dir}, found {len(files)}")
    metadata_path = files[0]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    rows = json.loads((metadata_path.parent / "chapters.json").read_text(encoding="utf-8"))
    if canonical_url(metadata["source_url"]) != url:
        raise ValueError("Source URL in downloaded EPUB metadata differs from requested URL")
    if not isinstance(rows, list) or not rows or len(rows) != metadata.get("chapter_count"):
        raise ValueError("Missing chapters or inconsistent chapter count: not recording an incomplete download")
    if chapter_range != "all":
        first, last = map(int, chapter_range.split("-"))
        expected = list(range(first, last + 1))
        if [item.get("position") for item in rows] != expected:
            raise ValueError("Chapter positions do not cover the requested inclusive range")
    for item in rows:
        filename = item.get("file", "")
        if not filename or Path(filename).name != filename:
            raise ValueError("Invalid chapter filename in manifest")
        if not (metadata_path.parent / filename).is_file():
            raise ValueError(f"Missing chapter file {filename}")
    if not (metadata_path.parent / "source.epub").is_file():
        raise ValueError("Missing source EPUB")
    now = now or datetime.now(timezone.utc)
    novel = next((n for n in registry["novels"] if canonical_url(n["url"]) == url), None)
    if novel is None:
        novel = {"url": url, "title": metadata.get("title", ""), "author": metadata.get("author", ""), "downloads": []}
        registry["novels"].append(novel)
    else:
        novel["title"] = metadata.get("title") or novel.get("title", "")
        novel["author"] = metadata.get("author") or novel.get("author", "")
    item = {
        "range": chapter_range,
        "status": "complete",
        "chapter_count": len(rows),
        "run_id": int(run_id),
        "run_url": f"https://github.com/RichardDaffern/Novel_Library/actions/runs/{run_id}",
        "artifact_id": int(artifact_id),
        "artifact_url": artifact_url,
        "completed_at_utc": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "expires_at_utc": (now + timedelta(days=retention_days)).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    novel["downloads"].append(item)
    return item


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["check", "record", "render"])
    p.add_argument("--registry", type=Path, default=Path("downloaded_novels.json"))
    p.add_argument("--markdown", type=Path, default=Path("DOWNLOADED_NOVELS.md"))
    p.add_argument("--url", default="")
    p.add_argument("--chapter-range", default="")
    p.add_argument("--force", action="store_true")
    p.add_argument("--downloads-dir", type=Path, default=Path("downloads"))
    p.add_argument("--run-id", default="")
    p.add_argument("--artifact-id", default="")
    p.add_argument("--artifact-url", default="")
    args = p.parse_args(argv)
    registry = read_registry(args.registry)
    if args.command == "check":
        skip = not args.force and already_available(registry, args.url, args.chapter_range)
        if skip:
            print(f"Already downloaded and artifact available: {canonical_url(args.url)} [{normalise_range(args.chapter_range)}]. Skipping download.", flush=True)
        else:
            print("Download permitted: new, expired, uncovered range, or Force selected.", flush=True)
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as out:
                out.write(f"skip={'true' if skip else 'false'}\n")
        return 0
    if args.command == "record":
        if not all((args.url, args.run_id, args.artifact_id, args.artifact_url)):
            p.error("record requires --url, --run-id, --artifact-id and --artifact-url")
        recorded = record_download(
            registry, args.url, args.chapter_range, args.downloads_dir,
            args.run_id, args.artifact_url, args.artifact_id
        )
        print(f"Completed novel download indexed: {args.url} [{recorded['range']}], {recorded['chapter_count']} chapters")
    write_registry(registry, args.registry, args.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
