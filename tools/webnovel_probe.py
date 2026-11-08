#!/usr/bin/env python3
"""Isolated, read-only feasibility probe for publicly visible WebNovel book metadata.

This is deliberately NOT a WebNovel chapter downloader. It does not visit
chapter pages, authenticate, unlock content, or create EPUB/TXT archives.
Run only against public book pages and respect the site's terms.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

MAX_HTML_BYTES = 4 * 1024 * 1024
BOOK_PATH = re.compile(r"^/book/(?:[a-zA-Z0-9_-]*_)?[0-9]{6,}/?$")


class WebNovelProbeError(ValueError):
    """Unsupported URL, inaccessible public page or missing metadata."""


def validate_book_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"webnovel.com", "www.webnovel.com"}
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not BOOK_PATH.fullmatch(parsed.path)
    ):
        raise WebNovelProbeError("Enter a public https://www.webnovel.com/book/<book-id> URL")
    return f"https://www.webnovel.com{parsed.path.rstrip('/')}"


def parse_public_book_metadata(html: str, url: str) -> dict:
    """Read title, author, and chapter count; never extract chapter bodies."""
    url = validate_book_url(url)
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("h1")
    og_title = soup.find("meta", attrs={"property": "og:title"})
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    if not title and og_title:
        title = (og_title.get("content") or "").split(" - WebNovel")[0].strip()
    if not title:
        raise WebNovelProbeError("Public book title was not found; the page layout may differ")

    # A bounded excerpt from the book header is enough for these fields.
    header_text = soup.get_text(" ", strip=True)[:6000]
    author_match = re.search(
        r"\bAuthor\s*:\s*(.+?)(?=\s+\d(?:[\d,]*)\s+Chapters\b|\s+\d+(?:\.\d+)?M\s+Views\b|\s+\d+(?:\.\d+)?\s+\(\d|$)",
        header_text, flags=re.IGNORECASE,
    )
    # Fallback: the first short author label visible near the top of the page.
    author = ""
    if author_match:
        author = author_match.group(1).strip()[:120]
    else:
        author_match = re.search(r"\bAuthor\s*:\s*([^\n]{1,60})", header_text, re.IGNORECASE)
        if author_match:
            author = author_match.group(1).strip()[:120]

    chapter_match = re.search(r"\b([0-9][0-9,]*)\s+Chapters\b", header_text, re.IGNORECASE)
    chapter_count = int(chapter_match.group(1).replace(",", "")) if chapter_match else None

    return {
        "platform": "webnovel",
        "url": url,
        "title": title,
        "author": author or None,
        "listed_chapters": chapter_count,
        "public_metadata_readable": True,
        "chapter_export_verified": False,
        "chapter_text_extracted": False,
    }


def probe_public_book(url: str, timeout_seconds: int = 12) -> dict:
    """Make one unauthenticated request to a book listing, not chapter pages."""
    url = validate_book_url(url)
    if not 1 <= timeout_seconds <= 30:
        raise ValueError("Timeout must be between 1 and 30 seconds")
    request = Request(
        url,
        headers={"User-Agent": "NovelLibraryMetadataProbe/0.1 (public book metadata only)"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if validate_book_url(response.geturl()) != url:
                raise WebNovelProbeError("Redirected away from requested public book page")
            html_bytes = response.read(MAX_HTML_BYTES + 1)
            if len(html_bytes) > MAX_HTML_BYTES:
                raise WebNovelProbeError("Book page exceeded metadata probe size limit")
            html = html_bytes.decode("utf-8", errors="replace")
    except (OSError, ValueError) as error:
        if isinstance(error, WebNovelProbeError):
            raise
        raise WebNovelProbeError(f"Public WebNovel book page could not be retrieved: {error}") from error
    return parse_public_book_metadata(html, url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="The public WebNovel /book/ URL to inspect")
    parser.add_argument(
        "--html-file", type=Path,
        help="Parse a supplied HTML fixture instead of contacting the website",
    )
    args = parser.parse_args(argv)
    try:
        url = validate_book_url(args.url)
        result = (
            parse_public_book_metadata(args.html_file.read_text(encoding="utf-8"), url)
            if args.html_file else probe_public_book(url)
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (WebNovelProbeError, OSError) as error:
        print(f"WebNovel metadata probe failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
