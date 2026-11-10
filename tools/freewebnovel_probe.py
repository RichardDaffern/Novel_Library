#!/usr/bin/env python3
"""FreeWebNovel public-page feasibility check; at most two chapter requests.

This is deliberately not a complete-novel downloader. It checks ordinary
public pages only, prints non-content diagnostics and does not save prose.
No login, browser sessions, proxies, CAPTCHA solving, paywall bypass or
unattended retries. Existing NovelFull workflows are not involved.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup

HOSTS = {"freewebnovel.com", "www.freewebnovel.com"}
BOOK_PATH = re.compile(r"^/novel/(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)/?$")
CHAPTER_PATH = re.compile(
    r"^/novel/(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)/chapter-(?P<number>[1-9][0-9]*)/?$"
)
BODY_SELECTORS = (".txt", "#chapter-content", ".chapter-content")
LOCK_TEXT = (
    "unlock this chapter", "subscribe to unlock",
    "purchase this chapter", "this chapter is locked",
)
MAX_BYTES = 3 * 1024 * 1024


class ProbeError(ValueError):
    """The site could not be checked without crossing an access boundary."""


class RefuseRedirect(HTTPRedirectHandler):
    """Reject redirects instead of following unexpected endpoints."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("Redirect encountered; stopped without following it")


def _valid_parts(url: str):
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ProbeError("Invalid URL") from exc
    if (
        parts.scheme != "https" or parts.hostname not in HOSTS
        or port is not None or parts.username or parts.password
        or parts.query or parts.fragment
    ):
        raise ProbeError("Use a public HTTPS freewebnovel.com URL without query or credentials")
    return parts


def validate_book_url(url: str) -> str:
    parts = _valid_parts(url)
    match = BOOK_PATH.fullmatch(parts.path)
    if not match:
        raise ProbeError("Expected a /novel/<book-slug> URL, not the /home page")
    return f"https://freewebnovel.com/novel/{match.group('slug')}"


def chapter_url(url: str, book_url: str):
    checked_book = validate_book_url(book_url)
    parts = _valid_parts(url)
    matched = CHAPTER_PATH.fullmatch(parts.path)
    if not matched or matched.group("slug") != checked_book.rsplit("/", 1)[-1]:
        raise ProbeError("Chapter URL does not belong to the selected novel")
    return (
        f"https://freewebnovel.com/novel/{matched.group('slug')}/"
        f"chapter-{int(matched.group('number'))}",
        int(matched.group("number")),
    )


def parse_catalogue(html: str, book_url: str) -> dict:
    book_url = validate_book_url(book_url)
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    title = heading.get_text(" ", strip=True) if heading else ""
    if not title or len(title) > 250:
        raise ProbeError("Novel title not found in ordinary catalogue page")
    chapters = {}
    for anchor in soup.select("a[href]"):
        absolute = urljoin(book_url + "/", anchor["href"])
        try:
            link, number = chapter_url(absolute, book_url)
        except ProbeError:
            continue
        if number not in (1, 2):
            continue
        label = anchor.get_text(" ", strip=True) or f"Chapter {number}"
        if number in chapters and chapters[number]["url"] != link:
            raise ProbeError(f"Conflicting Chapter {number} catalogue links")
        chapters[number] = {"position": number, "title": label, "url": link}
    if set(chapters) != {1, 2}:
        raise ProbeError(
            "Chapters 1 and 2 not found in the initial catalogue HTML. "
            "The site may require another page or an updated parser."
        )
    return {"title": title, "book_url": book_url, "chapters": [
        chapters[1], chapters[2],
    ]}


def inspect_chapter(html: str, *, position: int) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if "just a moment" in title or "attention required" in title:
        raise ProbeError("Access challenge page; stopped")
    for selector in BODY_SELECTORS:
        container = soup.select_one(selector)
        if container is None:
            continue
        for element in container.select("script,style,iframe,nav,button,aside,.ads,h4"):
            element.decompose()
        text = container.get_text("\n", strip=True)
        if any(marker in text.lower() for marker in LOCK_TEXT):
            raise ProbeError(f"Chapter {position} is locked; stopped")
        if len(text) < 200:
            raise ProbeError(f"Chapter {position} body unexpectedly short; stopped")
        return {
            "position": position,
            "characters": len(text),
            "paragraphs": sum(bool(p.strip()) for p in text.split("\n")),
            "sha256_prefix": sha256(text.encode("utf-8")).hexdigest()[:12],
            "selector": selector,
        }
    visible = soup.get_text(" ", strip=True).lower()
    if any(marker in visible for marker in LOCK_TEXT):
        raise ProbeError(f"Chapter {position} is locked; stopped")
    raise ProbeError(
        f"Chapter {position} has no recognised public text container; stopped"
    )


def fetch_public_html(url: str) -> str:
    _valid_parts(url)
    opener = build_opener(RefuseRedirect())
    request = Request(
        url, headers={"User-Agent": "NovelLibraryFeasibility/0.1"}
    )
    try:
        with opener.open(request, timeout=15) as response:
            if response.headers.get("cf-mitigated", "").lower() == "challenge":
                raise ProbeError("Cloudflare challenge response; stopped")
            if response.status != 200:
                raise ProbeError(f"HTTP {response.status}; stopped")
            if not response.headers.get_content_type() in ("text/html", "application/xhtml+xml"):
                raise ProbeError("Response was not HTML; stopped")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ProbeError("HTML response exceeds 3 MiB; stopped")
            return data.decode("utf-8-sig", errors="replace")
    except HTTPError as exc:
        raise ProbeError(f"Site returned HTTP {exc.code}; stopped") from exc
    except URLError as exc:
        raise ProbeError(f"Could not access public page: {exc.reason}") from exc


def probe(book_url, *, confirm_rights=False, catalog_only=False,
          fetcher=fetch_public_html, sleeper=time.sleep) -> dict:
    book_url = validate_book_url(book_url)
    if not catalog_only and not confirm_rights:
        raise ProbeError("--confirm-rights is required to fetch chapter text")
    info = parse_catalogue(fetcher(book_url), book_url)
    result = {
        "source": "FreeWebNovel",
        "title": info["title"],
        "book_url": book_url,
        "first_two_links": info["chapters"],
        "download_supported": False,
    }
    if catalog_only:
        return result
    inspected = []
    for chapter in info["chapters"]:
        sleeper(1)
        text = fetcher(chapter["url"])
        diagnostics = inspect_chapter(text, position=chapter["position"])
        inspected.append({**diagnostics, "title": chapter["title"]})
    result["chapter_checks"] = inspected
    result["retrieval_feasible_for_two_public_chapters"] = True
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book_url", help="https://freewebnovel.com/novel/book-slug")
    parser.add_argument("--catalog-only", action="store_true",
                        help="Check public catalogue without chapter requests")
    parser.add_argument("--confirm-rights", action="store_true",
                        help="Confirm that you have permission to archive the chapters")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(probe(
            args.book_url, confirm_rights=args.confirm_rights,
            catalog_only=args.catalog_only,
        ), ensure_ascii=False, indent=2))
        return 0
    except (ProbeError, OSError, ValueError) as exc:
        print(f"FreeWebNovel feasibility check stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
