#!/usr/bin/env python3
"""Two-chapter, public-page-only WebNovel feasibility adapter.

Makes at most three requests: one book catalogue and two linked public chapter pages.
No cookies, login, private endpoints, paywall handling, proxies, or rate-limit bypasses.
Writes no chapter text to Git. Does not call or modify NovelFull.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from tools.webnovel_probe import validate_book_url, parse_public_book_metadata
from tools.webnovel_export import export, ExportError

MAX_BYTES = 4 * 1024 * 1024
CHAPTER_URL = re.compile(r"^/book/(?:[a-zA-Z0-9_-]*_)?(\d{6,})/(?:[a-zA-Z0-9_-]*_)?(\d{6,})/?$")
# Keep selectors narrow to avoid accidentally archiving site navigation, ads or comments.
CONTENT_SELECTORS = (
    "div.cha-content", "div.chapter-content", "div#chapter-content",
    "div.chapter_content", "div#chapterContent", "article.chapter-content",
)
LOCK_MARKERS = ("unlock this chapter", "unlock chapter", "purchase this chapter",
                "subscribe to unlock", "premium chapter", "this chapter is locked")


class PublicChapterError(ValueError):
    pass


def _chapter_url(url, book_id):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.webnovel.com"
            or parsed.username or parsed.password or parsed.port is not None
            or parsed.query or parsed.fragment):
        raise PublicChapterError("Only public HTTPS WebNovel chapter URLs are supported")
    match = CHAPTER_URL.fullmatch(parsed.path)
    if match is None or match.group(1) != book_id:
        raise PublicChapterError("Chapter URL is not part of the selected public book")
    return "https://www.webnovel.com" + parsed.path.rstrip("/")


def public_first_two_links(book_html, book_url):
    book_url = validate_book_url(book_url)
    book_id = book_url.rsplit("_", 1)[-1].rsplit("/", 1)[-1]
    soup = BeautifulSoup(book_html, "html.parser")
    # The catalogue displays a "Latest Release" chapter link above its table
    # of contents; do not take the first two links in document order. Instead
    # identify *exactly* Chapters 1 and 2 by their visible numbered labels.
    found = {}
    for a in soup.find_all("a", href=True):
        link = urljoin(book_url, a["href"])
        try:
            checked = _chapter_url(link, book_id)
        except PublicChapterError:
            continue
        label = a.get_text(" ", strip=True)
        number_match = re.match(r"^\s*(?:\d+\s+)?chapter\s*([12])\b", label, flags=re.I)
        if not number_match:
            continue
        number = int(number_match.group(1))
        if number in found and found[number][0] != checked:
            raise PublicChapterError(f"Conflicting URLs for Chapter {number} in public catalogue")
        found[number] = (checked, label)
    if set(found) != {1, 2} or found[1][0] == found[2][0]:
        raise PublicChapterError("Two public chapter links not present in static book HTML")
    return [found[1], found[2]]


def _contains_lock_notice(text):
    """Look for a paywall notice in the candidate chapter body, not site chrome."""
    lowered = text.lower()
    return any(marker in lowered for marker in LOCK_MARKERS)


def parse_public_chapter(html, chapter_url, expected_title):
    soup = BeautifulSoup(html, "html.parser")
    # WebNovel's general navigation and dialogs can mention locked chapters
    # even when the current chapter is freely readable. Checking the entire
    # page first misclassifies those saved HTML files as locked.
    for selector in CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node:
            for unwanted in node.select("script,style,iframe,nav,button,aside"):
                unwanted.decompose()
            paragraphs = [p.get_text(" ", strip=True) for p in node.select("p")]
            text = "\n\n".join(p for p in paragraphs if p)
            if not text:
                text = node.get_text("\n", strip=True)
            if _contains_lock_notice(text):
                raise PublicChapterError("Page may contain locked content; stopped without exporting")
            if len(text) >= 100:
                return text
    # If no readable body was found, preserve the explicit locked-content error
    # when the only visible information is an unlock notice.
    if _contains_lock_notice(soup.get_text(" ", strip=True)):
        raise PublicChapterError("Page may contain locked content; stopped without exporting")
    raise PublicChapterError("Public chapter body selector not confirmed; no export attempted")


def get_public_html(url, timeout=12):
    request = Request(url, headers={"User-Agent": "NovelLibraryPublicFeasibility/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            if final_url != url:
                raise PublicChapterError("Redirected from the requested public URL")
            blob = response.read(MAX_BYTES + 1)
            if len(blob) > MAX_BYTES:
                raise PublicChapterError("Public page size limit exceeded")
            return blob.decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError) as exc:
        raise PublicChapterError(f"Public page unavailable: {exc}") from exc


def probe_two_chapters(book_url, output_dir, *, confirm_rights=False, fetcher=get_public_html):
    if not confirm_rights:
        raise PublicChapterError("Explicit --confirm-rights is required")
    book_url = validate_book_url(book_url)
    book_html = fetcher(book_url)
    metadata = parse_public_book_metadata(book_html, book_url)
    links = public_first_two_links(book_html, book_url)
    chapters = []
    for number, (url, label) in enumerate(links, 1):
        chapter_html = fetcher(url)
        body = parse_public_chapter(chapter_html, url, label)
        chapters.append({"position": number, "title": label, "text": body})
    return export({"source": "webnovel-public-with-user-confirmed-rights", "title": metadata["title"],
                   "author": metadata["author"] or "Unknown",
                   "chapters": chapters}, output_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book_url")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--confirm-rights", action="store_true",
                        help="Confirm you have permission to export these public chapters")
    args = parser.parse_args(argv)
    try:
        result = probe_two_chapters(args.book_url, args.output_dir, confirm_rights=args.confirm_rights)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PublicChapterError, ExportError, ValueError, OSError) as exc:
        print(f"Two-chapter public probe stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
