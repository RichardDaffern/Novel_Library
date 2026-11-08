#!/usr/bin/env python3
"""One-browser, two-public-chapter WebNovel retrieval feasibility check.

Uses an unmodified, temporary Chromium context with Playwright. Does not
spoof headers, persist or import sessions, evade anti-bot protections,
retry denials, read hidden APIs, handle paid chapters, or affect NovelFull.
Stops on any access challenge, locked content, or unfamiliar page layout.
Requires authorisation for local export. This remains a TWO-CHAPTER TEST.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup

from tools.webnovel_export import ExportError, export
from tools.webnovel_probe import validate_book_url
from tools.webnovel_public_two_chapter import (
    PublicChapterError,
    _chapter_url,
    parse_public_chapter,
    public_first_two_links,
)

PAGE_TIMEOUT_MS = 30000
PAGE_SETTLE_MS = 1800
# Cloudflare's documented challenge signal is the cf-mitigated header.
# Treat actual challenge page titles and a challenge-only body as fallbacks.
# Do NOT search all HTML markup for script names: genuine pages may contain
# challenge-related JS references without being challenge pages.
CHALLENGE_TITLES = ("just a moment...", "attention required! | cloudflare")
VISIBLE_CHALLENGE_TEXT = ("verify you are human", "checking your browser")


class BrowserProbeError(ValueError):
    """A two-chapter public browser retrieval could not safely complete."""


def _checked_page(page, url: str) -> str:
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    except Exception as exc:
        raise BrowserProbeError(f"Browser navigation failed: {exc}") from exc
    if response is None:
        raise BrowserProbeError("Browser navigation did not return an HTTP response")
    # https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/
    # This exact header distinguishes a real Cloudflare challenge response
    # from unrelated challenge-related strings in legitimate page scripts.
    if response.headers.get("cf-mitigated", "").lower() == "challenge":
        raise BrowserProbeError(
            "Confirmed Cloudflare challenge (cf-mitigated response header); "
            "stopped without bypassing it"
        )
    status = response.status
    if status >= 400:
        raise BrowserProbeError(f"Site returned HTTP {status}; no further request attempted")
    final_url = page.url.rstrip("/")
    if final_url != url.rstrip("/"):
        raise BrowserProbeError("Page redirected away from requested public URL")
    page.wait_for_timeout(PAGE_SETTLE_MS)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if any(marker in page_title for marker in CHALLENGE_TITLES):
        raise BrowserProbeError(
            "Browser displayed a Cloudflare challenge page title; "
            "stopped without bypassing it"
        )
    # Also reject a challenge-only page if the response header is absent,
    # without classifying ordinary pages with embedded challenge JS as blocked.
    visible = soup.get_text(" ", strip=True).lower()
    has_readable_structure = bool(
        soup.select_one(
            "div.cha-content, div.chapter-content, div#chapter-content, "
            "div.chapter_content, div#chapterContent, article.chapter-content"
        )
    )
    has_book_links = bool(soup.select_one('a[href*="/book/"]'))
    if not (has_readable_structure or has_book_links):
        if any(phrase in visible for phrase in VISIBLE_CHALLENGE_TEXT):
            raise BrowserProbeError(
                "Browser displayed a human-verification challenge without book/chapter content; "
                "stopped without bypassing it"
            )
    return html


def _do_probe(chromium, book_url, output_dir, chapter_urls=None, *, headless=False):
    browser = chromium.launch(headless=headless, timeout=PAGE_TIMEOUT_MS)
    try:
        context = browser.new_context()
        try:
            page = context.new_page()
            # Even with explicitly provided URLs, first verify the public
            # book page. This is at most three navigations total.
            html = _checked_page(page, book_url)
            book_id = book_url.rstrip("/").rsplit("/", 1)[-1].rsplit("_", 1)[-1]
            if chapter_urls:
                urls = [_chapter_url(link, book_id) for link in chapter_urls]
                if len(set(urls)) != 2:
                    raise BrowserProbeError("Two distinct chapter URLs are required")
                links = list(zip(urls, ["Chapter 1", "Chapter 2"]))
            else:
                try:
                    links = public_first_two_links(html, book_url)
                except PublicChapterError as exc:
                    raise BrowserProbeError(
                        "Could not find two public chapter links in the rendered book page. "
                        "Supply --chapter-1-url and --chapter-2-url copied from the site's normal chapter links."
                    ) from exc
            chapters = []
            for index, (url, label) in enumerate(links, start=1):
                chapter_html = _checked_page(page, url)
                try:
                    text = parse_public_chapter(chapter_html, url, label)
                except PublicChapterError as exc:
                    raise BrowserProbeError(f"Chapter {index}: {exc}") from exc
                chapters.append({"position": index, "title": label, "text": text})
                print(f"Browser public page {index}/2: readable chapter extracted")
            return chapters
        finally:
            context.close()
    finally:
        browser.close()


def browser_probe(book_url, output_dir, title, author, *,
                  confirm_rights=False, headless=False, chapter_urls=None,
                  chromium=None):
    if not confirm_rights:
        raise BrowserProbeError("Explicit --confirm-rights is required")
    book_url = validate_book_url(book_url)
    if (chapter_urls is not None and
            (len(chapter_urls) != 2 or any(not isinstance(u, str) for u in chapter_urls))):
        raise BrowserProbeError("Supply exactly two public chapter URLs")
    if chromium is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserProbeError(
                "Optional browser dependency missing. Install with "
                "'python -m pip install playwright' and "
                "'python -m playwright install chromium'."
            ) from exc
        with sync_playwright() as playwright:
            chapters = _do_probe(playwright.chromium, book_url, output_dir,
                                 chapter_urls, headless=headless)
    else:
        chapters = _do_probe(chromium, book_url, output_dir,
                             chapter_urls, headless=headless)
    return export({
        "source": "webnovel-public-with-user-confirmed-rights",
        "title": title,
        "author": author,
        "chapters": chapters,
    }, output_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book_url", help="Public WebNovel book URL")
    parser.add_argument("--book-title", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chapter-1-url", help="Public chapter 1 URL if catalogue does not expose links")
    parser.add_argument("--chapter-2-url", help="Public chapter 2 URL if catalogue does not expose links")
    parser.add_argument("--headless", action="store_true", help="Test with invisible browser; visible by default")
    parser.add_argument("--confirm-rights", action="store_true",
                        help="Confirm authorisation to export these public chapters locally")
    args = parser.parse_args(argv)
    if (args.chapter_1_url is None) != (args.chapter_2_url is None):
        parser.error("Provide both --chapter-1-url and --chapter-2-url, or neither")
    chapter_urls = [args.chapter_1_url, args.chapter_2_url] if args.chapter_1_url else None
    try:
        result = browser_probe(
            args.book_url, args.output_dir, args.book_title, args.author,
            confirm_rights=args.confirm_rights, headless=args.headless,
            chapter_urls=chapter_urls,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (BrowserProbeError, PublicChapterError, ExportError, OSError, ValueError) as exc:
        print(f"WebNovel browser test stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
