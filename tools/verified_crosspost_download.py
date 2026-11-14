#!/usr/bin/env python3
"""Download a registered author cross-post from FicHub and package a validated novel ZIP.

This is NOT a general Scribble Hub website scraper. It accepts only previously
verified Scribble Hub/FanFiction.net work pairs in verified_crossposts.json,
fetches the actual EPUB through FicHub's documented API, and validates both
the provenance and full chapter sequence before publishing a ZIP.

Never sends cookies or novel text to logging or source control. No automatic
retries, concurrent API calls, proxies or Cloudflare challenge workarounds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urljoin, urlsplit

import requests

from novel_downloader import epub_chapters
from tools.chunked_download import _epub
from tools.import_local_epub import (
    LocalImportError, _import_source_url, import_epub_to_zip, inspect_local_epub,
    MAX_INPUT_EPUB,
)
from tools.novel_covers import extract_epub_cover, write_cover

REGISTRY_FILE = Path(__file__).with_name("verified_crossposts.json")
API = "https://fichub.net/api/v0/epub"
USER_AGENT = (
    "Novel_Library-Crosspost/1.0 "
    "(+https://github.com/RichardDaffern/Novel_Library/issues)"
)


class CrosspostDownloadError(ValueError):
    """No permission, unverified crosspost or failed ebook integrity check."""


def _normalised(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _registry() -> dict:
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("scribblehub"), dict):
        raise CrosspostDownloadError("Invalid verified-crossposts registry")
    return data["scribblehub"]


def _verified_record(url: str, registry: dict | None = None) -> tuple[str, str, dict]:
    site, canonical = _import_source_url(url)
    if site != "ScribbleHub":
        raise CrosspostDownloadError("Expected a Scribble Hub novel series URL")
    match = re.fullmatch(
        r"https://www[.]scribblehub[.]com/series/([1-9][0-9]*)/(?:[a-z0-9-]+/)?",
        canonical,
    )
    if not match:
        raise CrosspostDownloadError("Invalid Scribble Hub series URL")
    series_id = match.group(1)
    mapping = _registry() if registry is None else registry
    entry = mapping.get(series_id)
    if not isinstance(entry, dict):
        raise CrosspostDownloadError(
            "No author-verified FanFiction.net cross-post is registered for this series. "
            "A matching title alone is not sufficient to select a different book."
        )
    if not isinstance(entry.get("fanfiction_url"), str):
        raise CrosspostDownloadError("Verified cross-post has no source URL")
    return canonical, series_id, entry


def _check_source_metadata(meta: dict, entry: dict) -> int:
    if not isinstance(meta, dict):
        raise CrosspostDownloadError("FicHub did not return valid story metadata")
    expected_title = entry["title"]
    expected_author = entry["author"]
    if (_normalised(str(meta.get("title", ""))) != _normalised(expected_title) or
            _normalised(str(meta.get("author", ""))) != _normalised(expected_author)):
        raise CrosspostDownloadError("FicHub title or author does not match the verified cross-post")
    u = urlsplit(str(meta.get("source", "")))
    source = urlsplit(entry["fanfiction_url"])
    if (u.scheme != "https" or u.hostname not in ("fanfiction.net", "www.fanfiction.net")
            or not re.fullmatch(r"/s/([1-9][0-9]*)(?:/.*)?", u.path)
            or u.path.split("/")[2] != source.path.split("/")[2]):
        raise CrosspostDownloadError("FicHub returned a different FanFiction.net work")
    count = meta.get("chapters")
    if type(count) is not int or not (entry["minimum_chapters"] <= count <= 20000):
        raise CrosspostDownloadError("Missing, stale or implausible FicHub chapter count")
    return count


def _epub_url(payload: dict) -> str:
    raw = payload.get("epub_url") or (payload.get("urls") or {}).get("epub")
    if not isinstance(raw, str) or not raw.startswith("/cache/epub/"):
        raise CrosspostDownloadError("FicHub supplied no verified EPUB download path")
    address = urljoin("https://fichub.net", raw)
    u = urlsplit(address)
    if (u.scheme != "https" or u.netloc != "fichub.net"
            or not u.path.startswith("/cache/epub/")
            or any(part in (".", "..") for part in u.path.split("/"))
            or u.fragment):
        raise CrosspostDownloadError("Unsafe EPUB download URL from FicHub")
    return address


def _expect_http_ok(response, operation: str) -> None:
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "")
        suffix = (f"; Retry-After: {retry_after}" if retry_after.isdigit() else "")
        raise CrosspostDownloadError("FicHub rate limit (HTTP 429); stop and try later" + suffix)
    if response.status_code != 200:
        raise CrosspostDownloadError(
            f"FicHub {operation} returned HTTP {response.status_code}; no retry attempted"
        )


def _save_epub(client, download_url: str, destination: Path) -> None:
    response = client.get(
        download_url, headers={"User-Agent": USER_AGENT, "Accept": "application/epub+zip"},
        timeout=90, allow_redirects=False, stream=True,
    )
    try:
        _expect_http_ok(response, "EPUB download")
        declared = response.headers.get("Content-Length", "")
        if declared.isdigit() and int(declared) > MAX_INPUT_EPUB:
            raise CrosspostDownloadError("EPUB exceeds the 300 MiB safety limit")
        size = 0
        with destination.open("wb") as file:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_INPUT_EPUB:
                    raise CrosspostDownloadError("EPUB exceeds the 300 MiB safety limit")
                file.write(chunk)
        if size < 1024:
            raise CrosspostDownloadError("Downloaded EPUB is unexpectedly small")
    finally:
        response.close()


def _story_sections(sections: list[dict], count: int, entry: dict) -> list[dict]:
    intro = entry["front_matter"]
    expected_first = _normalised(entry["first_chapter_title"])
    if (len(sections) == count + len(intro)
            and all(_normalised(sections[i]["title"]) == _normalised(title)
                    for i, title in enumerate(intro))
            and _normalised(sections[len(intro)]["title"]) == expected_first):
        story = sections[len(intro):]
    elif len(sections) == count and _normalised(sections[0]["title"]) == expected_first:
        story = sections
    else:
        raise CrosspostDownloadError(
            f"EPUB has {len(sections)} readable sections but FicHub reports "
            f"{count} story chapters; unrecognised front matter or missing chapters"
        )
    if len(story) != count:
        raise CrosspostDownloadError("Incomplete story after excluding verified front matter")
    for checkpoint in entry.get("chapter_checkpoints", []):
        position = checkpoint["position"]
        if len(story) >= position and (
                _normalised(story[position - 1]["title"]) !=
                _normalised(checkpoint["title"])):
            raise CrosspostDownloadError(f"Story chapter {position} failed the cross-post identity check")
    return story


def _prepare_epub(
    raw_epub: Path, working_folder: Path, url: str, count: int, entry: dict
) -> Path:
    book, sections = epub_chapters(raw_epub)
    if (_normalised(book.get("title", "")) != _normalised(entry["title"]) or
            _normalised(book.get("author", "")) != _normalised(entry["author"])):
        raise CrosspostDownloadError("Downloaded EPUB metadata does not match the verified book")
    chapters = _story_sections(sections, count, entry)
    working_folder.mkdir()
    rows = []
    for number, chapter in enumerate(chapters, start=1):
        title = chapter["title"].strip()
        body = chapter["text"].strip()
        if not title or not body:
            raise CrosspostDownloadError(f"Empty chapter {number} in cross-post EPUB")
        filename = f"chapter_{number:05d}.txt"
        data = f"{title}\n\n{body}\n".encode("utf-8")
        (working_folder / filename).write_bytes(data)
        rows.append({
            "position": number,
            "chapter_number": number,
            "title": title,
            "file": filename,
            "word_count": len(body.split()),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

    cover_path = None
    cover = extract_epub_cover(raw_epub)
    if cover is not None:
        cover_path = working_folder / write_cover(working_folder, *cover)
    _epub(
        working_folder, rows, book["title"], book["author"],
        book.get("language") or "en", url,
        description=book.get("description") or "",
        cover_path=cover_path,
        genres=book.get("genres") if isinstance(book.get("genres"), list) else None,
        status=book.get("status") or "",
    )
    generated = working_folder / "source.epub"
    _, verified_count = inspect_local_epub(generated)
    if verified_count != count:
        raise CrosspostDownloadError("Rebuilt EPUB lost chapters before packaging")
    return generated


def download_verified_crosspost(
    url: str, output_dir: Path, *, confirm_rights: bool = False,
    replace: bool = False, client=None, registry: dict | None = None,
) -> Path:
    """Retrieve a registered author's cross-post and atomically package a ZIP.

    The optional client/registry parameters are for network-free test fixtures.
    """
    if not confirm_rights:
        raise CrosspostDownloadError("Confirm you are permitted to archive this work with --confirm-rights")
    canonical, series_id, entry = _verified_record(url, registry)
    output_dir = Path(output_dir)
    identity = hashlib.sha256(
        f"https://www.scribblehub.com/series/{series_id}/".encode("utf-8")
    ).hexdigest()[:12]
    output = output_dir / f"novel-{identity}.zip"
    if output.exists() and not replace:
        raise CrosspostDownloadError("A novel ZIP already exists; use --replace to update it")

    owned_session = client is None
    if owned_session:
        client = requests.Session()
    try:
        response = client.get(
            API, params={"q": entry["fanfiction_url"]},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=60, allow_redirects=False,
        )
        try:
            _expect_http_ok(response, "metadata/export request")
            payload = response.json()
        finally:
            response.close()
        if not isinstance(payload, dict) or payload.get("err") != 0:
            raise CrosspostDownloadError("FicHub declined to export this work")
        count = _check_source_metadata(payload.get("meta"), entry)
        link = _epub_url(payload)
        with tempfile.TemporaryDirectory(prefix="verified-crosspost-") as directory:
            temp = Path(directory)
            raw = temp / "download.epub"
            _save_epub(client, link, raw)
            # Validates structure, uncompressed sizes and ZIP CRC before parsing.
            inspect_local_epub(raw)
            prepared = _prepare_epub(raw, temp / "prepared", canonical, count, entry)
            # Uses the existing atomic ZIP writer and chapter SHA-256 verifier.
            return import_epub_to_zip(
                prepared, output_dir, canonical, confirm_rights=True, replace=replace
            )
    finally:
        if owned_session:
            client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Registered Scribble Hub series URL")
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("Downloaded_Novels"))
    parser.add_argument("--replace", action="store_true",
                        help="Replace an existing validated ZIP only after the new ZIP passes validation")
    opts = parser.parse_args(argv)
    try:
        path = download_verified_crosspost(
            opts.url, opts.output_dir, confirm_rights=opts.confirm_rights,
            replace=opts.replace,
        )
        print(f"Created validated novel ZIP: {path}")
        return 0
    except (CrosspostDownloadError, LocalImportError, ValueError,
            OSError, requests.RequestException) as exc:
        print(f"Cross-post download failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
