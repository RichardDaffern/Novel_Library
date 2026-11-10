#!/usr/bin/env python3
"""Archive explicitly authorised public FreeWebNovel chapter ranges.

Separate from FanFicFare and NovelFull. No login, paywall/Cloudflare bypass,
rotating proxies, concurrent requests within one batch or automatic retries.
Each invocation is capped at 100 consecutive numbered chapters. The Github
workflow partitions full books and validates every chapter before assembly.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from novel_downloader import epub_chapters, slugify
from tools.chunked_download import _epub
from tools.freewebnovel_probe import (
    ProbeError, BODY_SELECTORS, LOCK_TEXT, chapter_url,
    fetch_public_html, parse_catalogue, validate_book_url,
)

MAX_PER_RUN = 100
MAX_TOTAL = 50000
MIN_BODY_CHARS = 200
CHAPTER_HEADER = re.compile(r"\bchapter\s*([0-9]+)\b", re.IGNORECASE)


class DownloadError(ValueError):
    """Chapter data is unavailable, incomplete or not safe to export."""


def book_details(html: str, url: str) -> dict:
    """Read a public catalogue without mistaking other novels for chapters."""
    url = validate_book_url(url)
    first = parse_catalogue(html, url)
    soup = BeautifulSoup(html, "html.parser")
    numbers = set()
    for anchor in soup.select("a[href]"):
        absolute = urljoin(url + "/", anchor.get("href", ""))
        try:
            _, number = chapter_url(absolute, url)
        except ProbeError:
            continue
        numbers.add(number)
    if 1 not in numbers or 2 not in numbers:
        raise DownloadError("Public catalogue does not include the opening chapters")
    total = max(numbers)
    if total < 2 or total > MAX_TOTAL:
        raise DownloadError("Published chapter count outside supported range")
    # The site displays the latest six chapter links before the first 40.
    # Their highest number provides an upper bound for sequential chapter URLs.
    # We verify every chosen chapter page; missing chapters fail, never skip.
    author_node = soup.select_one('a[href*="/author/"]')
    author = author_node.get_text(" ", strip=True) if author_node else "Unknown"
    return {
        "title": first["title"],
        "author": author[:240] or "Unknown",
        "numChapters": total,
        "source_url": url,
        "first_two_links": first["chapters"],
        "count_basis": "largest numbered chapter link in public catalogue",
    }


def extract_chapter(html: str, number: int, fallback_title: str = "") -> dict:
    """Extract only the reader's public chapter body and validate its number."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.title.get_text(" ", strip=True) if soup.title else ""
    if "just a moment" in title_tag.lower() or "attention required" in title_tag.lower():
        raise DownloadError("Site access challenge; stopped")
    headings = [h.get_text(" ", strip=True) for h in soup.select("h1,h2,h3")]
    header = next(
        (text for text in headings if CHAPTER_HEADER.search(text)),
        next((text for text in (title_tag,) if CHAPTER_HEADER.search(text)), ""),
    )
    if header:
        parsed = CHAPTER_HEADER.search(header)
        if parsed and int(parsed.group(1)) != number:
            raise DownloadError(
                f"Expected Chapter {number}, but the page identifies Chapter {parsed.group(1)}"
            )
    title = header if header and len(header) <= 240 else fallback_title or f"Chapter {number}"
    for selector in BODY_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        for unwanted in node.select(
            "script,style,iframe,nav,button,aside,form,"
            ".ads,.advertisement,[id*='advert'],[class*='advert']"
        ):
            unwanted.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in node.select("p")]
        if paragraphs:
            text = "\n\n".join(p for p in paragraphs if p)
        else:
            text = "\n\n".join(s.strip() for s in node.stripped_strings if s.strip())
        if any(marker in text.lower() for marker in LOCK_TEXT):
            raise DownloadError(f"Chapter {number} appears locked; stopped")
        if len(text) < MIN_BODY_CHARS:
            raise DownloadError(
                f"Chapter {number} body is only {len(text)} characters; stopped"
            )
        return {"title": title, "text": text}
    visible = soup.get_text(" ", strip=True).lower()
    if any(marker in visible for marker in LOCK_TEXT):
        raise DownloadError(f"Chapter {number} appears locked; stopped")
    raise DownloadError(f"Chapter {number} reader body was not recognised")


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _validate_saved_row(book: Path, row: dict, number: int) -> bool:
    if row.get("position") != number:
        return False
    filename = row.get("file", "")
    if not isinstance(filename, str) or Path(filename).name != filename:
        return False
    chapter_file = book / filename
    return (
        chapter_file.is_file()
        and chapter_file.stat().st_size >= MIN_BODY_CHARS
        and sha256(chapter_file.read_bytes()).hexdigest() == row.get("sha256")
    )


def download_range(
    url: str, first: int, last: int, output_dir: Path, *,
    confirm_rights=False, fetcher=fetch_public_html, sleeper=time.sleep,
) -> dict:
    if not confirm_rights:
        raise DownloadError("--confirm-rights is required before requests")
    url = validate_book_url(url)
    if first < 1 or last < first or last - first + 1 > MAX_PER_RUN:
        raise DownloadError("A batch must contain 1 to 100 consecutive chapters")
    html = fetcher(url)
    details = book_details(html, url)
    if last > details["numChapters"]:
        raise DownloadError(
            f"Requested chapter {last} exceeds published chapter {details['numChapters']}"
        )
    name = slugify(details["title"]) + f"-chapters-{first:05d}-{last:05d}"
    book = Path(output_dir) / name
    book.mkdir(parents=True, exist_ok=True)
    checkpoint = book / ".progress.json"
    prior = {}
    if checkpoint.exists():
        data = json.loads(checkpoint.read_text(encoding="utf-8"))
        if (data.get("url"), data.get("first"), data.get("last")) != (url, first, last):
            raise DownloadError("Existing checkpoint belongs to a different book or range")
        prior = {row["position"]: row for row in data.get("chapters", [])}
    elif (book / "chapters.json").exists():
        rows = json.loads((book / "chapters.json").read_text(encoding="utf-8"))
        if all(
            _validate_saved_row(book, row, n)
            for n, row in zip(range(first, last + 1), rows)
        ) and len(rows) == last - first + 1 and (book / "source.epub").is_file():
            print(f"Verified existing {len(rows)} chapters; no new requests", flush=True)
            return {"title": details["title"], "author": details["author"],
                    "chapter_count": len(rows), "source_url": url, "output_dir": str(book)}
    expected_titles = {
        record["position"]: record["title"] for record in details["first_two_links"]
    }
    written = {}
    for number in range(first, last + 1):
        if number in prior and _validate_saved_row(book, prior[number], number):
            written[number] = prior[number]
            print(f"[{number-first+1}/{last-first+1}] reused Chapter {number}", flush=True)
            continue
        # One sequential public request per chapter; no automatic retries.
        sleeper(1)
        chapter_html = fetcher(f"{url}/chapter-{number}")
        item = extract_chapter(
            chapter_html, number, expected_titles.get(number, f"Chapter {number}")
        )
        if any(
            row.get("sha256") == sha256(
                (item["title"] + "\n\n" + item["text"].strip() + "\n").encode("utf-8")
            ).hexdigest()
            for row in written.values()
        ):
            raise DownloadError(f"Chapter {number} repeats an earlier chapter")
        name_txt = f"chapter_{number:05d}.txt"
        content = f"{item['title']}\n\n{item['text'].strip()}\n"
        (book / name_txt).write_text(content, encoding="utf-8")
        row = {
            "position": number, "chapter_number": number, "title": item["title"],
            "file": name_txt, "word_count": len(item["text"].split()),
            "sha256": sha256(content.encode("utf-8")).hexdigest(),
        }
        written[number] = row
        _write_json(checkpoint, {
            "url": url, "first": first, "last": last,
            "chapters": [written[key] for key in sorted(written)],
        })
        print(f"[{number-first+1}/{last-first+1}] Chapter {number} saved", flush=True)

    rows = [written[number] for number in range(first, last + 1)]
    if not all(_validate_saved_row(book, row, number)
               for number, row in zip(range(first, last+1), rows)):
        raise DownloadError("Chapter checksum verification failed before EPUB assembly")
    _epub(book, rows, details["title"], details["author"], "en", url)
    _, chapters = epub_chapters(book / "source.epub")
    if len(chapters) != len(rows):
        raise DownloadError("EPUB verification failed: missing chapter pages")
    metadata = {
        "title": details["title"], "author": details["author"],
        "language": "en", "source_url": url, "chapter_count": len(rows),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "format": "epub", "chapter_files": "UTF-8 TXT",
    }
    _write_json(book / "chapters.json", rows)
    _write_json(book / "metadata.json", metadata)
    checkpoint.unlink(missing_ok=True)
    return {"title": details["title"], "author": details["author"],
            "chapter_count": len(rows), "source_url": url, "output_dir": str(book)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="HTTPS FreeWebNovel /novel/<slug> URL")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--chapter-range", help="Inclusive 1-based range, maximum 100")
    parser.add_argument("--output-dir", type=Path, default=Path("downloads"))
    parser.add_argument("--confirm-rights", action="store_true")
    args = parser.parse_args(argv)
    try:
        url = validate_book_url(args.url)
        if args.list_only:
            if not args.confirm_rights:
                raise DownloadError("--confirm-rights is required")
            print(json.dumps(book_details(fetch_public_html(url), url),
                             ensure_ascii=False, indent=2))
            return 0
        if not args.chapter_range:
            raise DownloadError(
                "--chapter-range is required. Use GitHub Actions for a complete novel."
            )
        match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", args.chapter_range)
        if not match:
            raise DownloadError("Chapter range must be START-END, e.g. 1-2")
        first, last = map(int, match.groups())
        result = download_range(
            url, first, last, args.output_dir, confirm_rights=args.confirm_rights
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProbeError, DownloadError, OSError, ValueError) as exc:
        print(f"FreeWebNovel downloader stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
