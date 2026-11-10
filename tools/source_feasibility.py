#!/usr/bin/env python3
"""Offline feasibility analysis of four possible novel sources.

This is NOT a network crawler or novel downloader. Read locally saved HTML
from a book information page, optional chapter list, and at most TWO chapter
pages, without contacting the websites, logging prose, or creating EPUBs.
Access/download permissions differ by site. WTR-Lab prohibits automated
requests and downloading absent permission; never bypass locks or challenges.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

SITES = {
    "novelfire.net": ("NovelFire", re.compile(r"^/book/[a-z0-9]+(?:-[a-z0-9]+)*/?$")),
    "lightnovelpub.com": ("LightNovelPub", re.compile(r"^/novel/[a-z0-9]+(?:-[a-z0-9]+)*/?$")),
    # WTR-Lab changed /serie-<id> to /en/novel/<id>/<slug> in 2025.
    "wtr-lab.com": ("WTRLab", re.compile(
        r"^/(?:en/)?novel/[1-9][0-9]*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)?/?$"
    )),
    "royalroad.com": ("RoyalRoad", re.compile(
        r"^/fiction/[1-9][0-9]*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)?/?$"
    )),
}
MAX_HTML_BYTES = 4 * 1024 * 1024
LOCK_MARKERS = (
    "purchase this chapter", "pay to unlock", "chapter is locked",
    "please complete captcha", "verify you are human",
    "unlock chapter", "requires tickets", "premium chapter",
    "just a moment...", "enable javascript and cookies to continue",
)
CHAPTER_SELECTORS = (
    "#chapter-content", "#chr-content", "#content", ".chapter-content",
    ".chapter-body", ".chapter-text", ".reading-content", "#reader-content",
)


class SourceProbeError(ValueError):
    """Unsupported URL, missing saved input, or unreliable chapter HTML."""


def validate_book_url(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise SourceProbeError("Invalid URL") from exc
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "lightnovelpub.org":
        raise SourceProbeError(
            "The old lightnovelpub.org site has shut down; "
            "do not assume a new site is an equivalent content source"
        )
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or port is not None or parsed.query or parsed.fragment
            or host not in SITES):
        raise SourceProbeError("Use a supported, public HTTPS novel BOOK URL without query strings")
    label, pattern = SITES[host]
    if not pattern.fullmatch(parsed.path):
        raise SourceProbeError(f"Expected a {label} book URL, not a chapter or homepage")
    clean_path = parsed.path.rstrip("/")
    return label, f"https://{host}{clean_path}"


def _saved_html(path: Path) -> str:
    if path.suffix.casefold() not in (".html", ".htm"):
        raise SourceProbeError(f"Expected an HTML file: {path}")
    if not path.is_file():
        raise SourceProbeError(f"File missing: {path}")
    if path.stat().st_size > MAX_HTML_BYTES:
        raise SourceProbeError(f"HTML file exceeds 4 MiB: {path.name}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def parse_book_info(html: str, url: str) -> dict:
    site, canonical_url = validate_book_url(url)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1, h3.title, h2.title, [itemprop='name']")
    if not title:
        raise SourceProbeError("Book title missing; page may be an access challenge")
    title_text = title.get_text(" ", strip=True)
    if not title_text or len(title_text) > 260:
        raise SourceProbeError("Book title is empty or implausibly long")
    if any(marker in soup.get_text(" ", strip=True).lower() for marker in LOCK_MARKERS):
        raise SourceProbeError("Page contains access-control indicators")
    author = soup.select_one("[itemprop='author'], a[href*='/author/'], .author a")
    author_name = author.get_text(" ", strip=True) if author else ""
    if not author_name:
        # No assumed author: unknown is different from a misleading placeholder.
        author_name = None
    summary = soup.select_one(
        "#synopsis, #summary, .summary .content, .novel-summary, "
        ".summary-content, .desc-text, [itemprop='description']"
    )
    synopsis = summary.get_text("\n", strip=True)[:6000] if summary else None
    # Site templates differ: report a count only if it is actually present.
    visible = soup.get_text(" ", strip=True)
    count_match = re.search(r"(?i)\b([0-9][0-9,]{0,7})\s*chapters?\b", visible)
    chapters = int(count_match.group(1).replace(",", "")) if count_match else None
    return {
        "website": site, "url": canonical_url, "title": title_text,
        "author": author_name,
        "chapter_count_reported": chapters,
        "synopsis_present": bool(synopsis),
        "synopsis_characters": len(synopsis or ""),
    }


def parse_chapter_links(html: str, book_url: str) -> list[dict]:
    site, canonical = validate_book_url(book_url)
    parsed = urlsplit(canonical)
    book_path = parsed.path
    results: dict[int | str, dict] = {}
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        candidate = urljoin(canonical + "/", link.get("href", ""))
        parts = urlsplit(candidate)
        if (parts.scheme != "https" or
                (parts.hostname or "").removeprefix("www.") !=
                (parsed.hostname or "").removeprefix("www.")
                or parts.query or parts.fragment):
            continue
        if site == "RoyalRoad":
            # Royal Road IDs are not sequential chapter positions. Order here
            # is the order in the SAVED table of contents, not by chapter ID.
            match = re.fullmatch(
                re.escape(book_path) +
                r"/chapter/([1-9][0-9]*)(?:/[a-z0-9-]+)?/?",
                parts.path,
            )
            if not match:
                continue
            number: int | str = match.group(1)
            if number in results:
                continue
            results[number] = {
                "position": len(results) + 1,
                "chapter_id": number,
                "url": candidate.rstrip("/"),
                "title": link.get_text(" ", strip=True)[:250] or
                         f"Chapter {len(results) + 1}",
            }
        else:
            # Book-local numbered chapter links; WTR-Lab currently uses
            # /en/novel/<id>/<slug>/chapter-1. Never guess non-numeric IDs.
            match = re.fullmatch(
                re.escape(book_path) + r"/chapter-([1-9][0-9]*)/?",
                parts.path,
            )
            if not match:
                continue
            number = int(match.group(1))
            if number in results:
                continue
            results[number] = {
                "position": number,
                "url": candidate.rstrip("/"),
                "title": link.get_text(" ", strip=True)[:250] or
                         f"Chapter {number}",
            }
    if site == "RoyalRoad":
        return list(results.values())
    return [results[key] for key in sorted(results)]


def probe_saved_chapter(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    visible = soup.get_text(" ", strip=True).casefold()
    if any(marker in visible for marker in LOCK_MARKERS):
        raise SourceProbeError("Saved chapter indicates an access challenge or locked content")
    content = None
    selected = ""
    for selector in CHAPTER_SELECTORS:
        content = soup.select_one(selector)
        if content is not None:
            selected = selector
            break
    if content is None:
        raise SourceProbeError(
            "No verified chapter-text container found; refusing to export site furniture"
        )
    # Work on a detached copy so that scripts, controls and adverts cannot
    # inflate chapter metrics or end up in a later exporter.
    copy = BeautifulSoup(str(content), "html.parser")
    for tag in copy.select("script, style, nav, header, footer, form, button, iframe"):
        tag.decompose()
    paragraphs = [
        tag.get_text(" ", strip=True)
        for tag in copy.select("p")
        if tag.get_text(" ", strip=True)
    ]
    if len(paragraphs) >= 3:
        plain = "\n\n".join(paragraphs)
    else:
        plain = copy.get_text("\n", strip=True)
    if len(plain) < 350 or len(plain.split()) < 65:
        raise SourceProbeError("Saved chapter has insufficient verified narrative text")
    # Report dimensions and hash only: never print or save copied chapter prose.
    return {
        "selector": selected,
        "characters": len(plain),
        "words": len(plain.split()),
        "paragraphs": max(len(paragraphs), len(plain.splitlines())),
        "sha256": sha256(plain.encode("utf-8")).hexdigest(),
    }


def analyse_saved_pages(book_url: str, book_html: str,
                        index_html: str | None = None,
                        chapters: list[str] | None = None,
                        confirm_rights: bool = False) -> dict:
    result = parse_book_info(book_html, book_url)
    links = parse_chapter_links(index_html or book_html, book_url)
    result.update(
        chapter_links_found_on_supplied_page=len(links),
        first_two_linked_chapters=links[:2],
        chapter_content_tested=0,
        chapter_checks=[],
        download_supported=False,  # A static feasibility check is not a working downloader.
    )
    chapters = chapters or []
    if len(chapters) > 2:
        raise SourceProbeError("At most two saved chapters may be inspected")
    if chapters and not confirm_rights:
        raise SourceProbeError("--confirm-rights is required for saved chapter text")
    for i, html in enumerate(chapters, 1):
        result["chapter_checks"].append({"sample": i, **probe_saved_chapter(html)})
    result["chapter_content_tested"] = len(chapters)
    result["two_chapter_static_feasible"] = len(chapters) == 2
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book_url", help="Full HTTPS public book URL")
    parser.add_argument("--book-html", type=Path, required=True,
                        help="Locally saved book information page (.html)")
    parser.add_argument("--index-html", type=Path,
                        help="Locally saved chapter-list page (.html)")
    parser.add_argument("--chapter-html", type=Path, action="append", default=[],
                        help="Locally saved chapter HTML (maximum two; no online requests)")
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--report", type=Path,
                        help="Optional JSON report path (contains metadata, not chapter text)")
    args = parser.parse_args(argv)
    try:
        if len(args.chapter_html) > 2:
            raise SourceProbeError("Maximum of two chapter HTML files")
        result = analyse_saved_pages(
            args.book_url,
            _saved_html(args.book_html),
            _saved_html(args.index_html) if args.index_html else None,
            [_saved_html(path) for path in args.chapter_html],
            confirm_rights=args.confirm_rights,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)
        if args.report:
            args.report.write_text(rendered + "\n", encoding="utf-8")
        return 0
    except (OSError, SourceProbeError) as exc:
        print(f"Source feasibility check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
