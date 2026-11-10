#!/usr/bin/env python3
"""Cover-only utilities for public novel book pages and source EPUBs.

No chapter requests. Supports JPEG/PNG covers, converts WebP/GIF to JPEG
for EPUB 2 compatibility, limits image bytes/pixels, and avoids redirects
to non-public endpoints.
"""
from __future__ import annotations

from io import BytesIO
import ipaddress
from pathlib import Path
import posixpath
import re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
SOURCE_HOSTS = {"novelfull.com", "freewebnovel.com"}
BOOK_PATH = re.compile(r"^/novel/[a-z0-9]+(?:-[a-z0-9]+)*/?$")
NOVELFULL_PATH = re.compile(r"^/[a-z0-9_-]+\.html$")
SUPPORTED = {"JPEG": ".jpg", "PNG": ".png"}


class CoverError(ValueError):
    """The remote image or embedded cover was absent or unsuitable."""


def validate_public_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        port = parts.port
        addr = ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        addr = None
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError as exc:
            raise CoverError("Malformed URL") from exc
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https" or not host or parts.username or parts.password
            or port not in (None, 443)
            or host == "localhost" or host.endswith((".local", ".internal"))
            or host.endswith(".localhost") or host.startswith("localhost.")
            or (addr is not None and not addr.is_global)
            or "." not in host):
        raise CoverError("Only public HTTPS image URLs are allowed")
    return value


def validate_book_url(url: str) -> str:
    validate_public_url(url)
    p = urlsplit(url)
    host = (p.hostname or "").removeprefix("www.").lower()
    if host not in SOURCE_HOSTS or p.query or p.fragment:
        raise CoverError("Unsupported novel book URL")
    if host == "novelfull.com" and not NOVELFULL_PATH.fullmatch(p.path):
        raise CoverError("Expected a NovelFull /book-title.html URL")
    if host == "freewebnovel.com" and not BOOK_PATH.fullmatch(p.path):
        raise CoverError("Expected a FreeWebNovel /novel/book-title URL")
    return url


class SafeImageRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        if urlsplit(newurl).scheme != "https":
            raise CoverError("Image redirected away from HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_html(url: str) -> str:
    validate_book_url(url)
    # Book page redirects are refused; accidental redirect-to-home could
    # otherwise produce a website logo instead of a book-specific cover.
    class NoPageRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise CoverError("Book page redirected; stopped")

    opener = build_opener(NoPageRedirect())
    try:
        with opener.open(Request(url, headers={
            "User-Agent": "NovelLibraryCoverFetcher/1.0"
        }), timeout=20) as response:
            if response.headers.get("cf-mitigated", "").lower() == "challenge":
                raise CoverError("Website access challenge; stopped")
            if response.headers.get_content_type() not in ("text/html", "application/xhtml+xml"):
                raise CoverError("Novel book page did not return HTML")
            data = response.read(MAX_HTML_BYTES + 1)
        if len(data) > MAX_HTML_BYTES:
            raise CoverError("Novel book page exceeds size limit")
        html = data.decode("utf-8-sig", errors="replace")
        title = BeautifulSoup(html, "html.parser").title
        if title and "just a moment" in title.get_text(" ", strip=True).lower():
            raise CoverError("Website access challenge; stopped")
        return html
    except (HTTPError, URLError) as exc:
        raise CoverError(f"Novel book page unavailable: {exc}") from exc


def _image_candidates(html: str, book_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    # Prefer book-specific cover tags. Site layouts may change, so use a
    # conservative fallback to OpenGraph metadata rather than the first image.
    selectors = (
        # FanFicFare's live NovelFull adapter uses div.book > img;
        # the earlier .book-img selector missed all 89 indexed books.
        "div.book img",
        ".book-img img", ".book-cover img", ".book-image img",
        ".novel-cover img", ".bookpic img", ".book-pic img",
        ".detail-cover img", ".details .cover img",
        ".book-intro img", "img.cover", "img[itemprop='image']",
    )
    for selector in selectors:
        for img in soup.select(selector):
            for key in ("data-src", "data-original", "data-lazy-src", "src"):
                if img.get(key):
                    candidates.append(img[key])
                    break
    for tag in soup.select("meta[property='og:image'],meta[name='twitter:image']"):
        if tag.get("content"):
            candidates.append(tag["content"])
    # If no structural cover selector matched, use a matching-alt image.
    if not candidates:
        # NovelFull book titles are h3.title, not h1.
        title = soup.select_one("h3.title, h1, h2.title")
        text = title.get_text(" ", strip=True).casefold() if title else ""
        for img in soup.select("img[alt]"):
            alt = img.get("alt", "").strip().casefold()
            if alt and text and (alt in text or text in alt):
                candidates.append(img.get("data-src") or img.get("src") or "")
    result = []
    for candidate in candidates:
        if not candidate or candidate.startswith("data:"):
            continue
        url = urljoin(book_url, candidate)
        try:
            validate_public_url(url)
        except CoverError:
            continue
        if url not in result:
            result.append(url)
    return result


def fetch_image(url: str, referer: str = "") -> bytes:
    validate_public_url(url)
    headers = {"User-Agent": "NovelLibraryCoverFetcher/1.0", "Accept": "image/*"}
    if referer:
        validate_book_url(referer)
        headers["Referer"] = referer
    try:
        opener = build_opener(SafeImageRedirect())
        with opener.open(Request(url, headers=headers), timeout=20) as response:
            if response.headers.get("cf-mitigated", "").lower() == "challenge":
                raise CoverError("Image endpoint returned an access challenge")
            data = response.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise CoverError("Cover exceeds 8 MiB")
        return data
    except (HTTPError, URLError) as exc:
        raise CoverError(f"Cover image unavailable: {exc}") from exc


def validate_image(data: bytes) -> tuple[bytes, str]:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise CoverError("Empty or oversized cover image")
    try:
        with Image.open(BytesIO(data)) as image:
            fmt = image.format
            if image.width < 32 or image.height < 48:
                raise CoverError("Image is too small to be a book cover")
            if image.width * image.height > MAX_PIXELS:
                raise CoverError("Cover dimensions are too large")
            image.load()
            if fmt in SUPPORTED:
                return data, SUPPORTED[fmt]
            if fmt in ("WEBP", "GIF"):
                output = BytesIO()
                image.convert("RGB").save(output, "JPEG", quality=90, optimize=True)
                converted = output.getvalue()
                if len(converted) > MAX_IMAGE_BYTES:
                    raise CoverError("Converted image exceeds 8 MiB")
                return converted, ".jpg"
            raise CoverError(f"Unsupported cover image format: {fmt}")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise CoverError("Invalid or unsafe image data") from exc


def download_site_cover(book_url: str, *, html: str | None = None,
                        html_fetcher=fetch_html, image_fetcher=fetch_image
                        ) -> tuple[bytes, str, str]:
    """Return validated cover bytes, file extension, and source image URL."""
    validate_book_url(book_url)
    page = html if html is not None else html_fetcher(book_url)
    candidates = _image_candidates(page, book_url)
    if not candidates:
        raise CoverError("No cover image found on the book information page")
    errors = []
    for image_url in candidates[:5]:
        try:
            data, extension = validate_image(image_fetcher(image_url, book_url))
            return data, extension, image_url
        except (CoverError, OSError) as exc:
            errors.append(str(exc))
    raise CoverError("No suitable book cover available: " + "; ".join(errors[:3]))


def extract_epub_cover(epub_path: Path) -> tuple[bytes, str] | None:
    """Read only the cover image from a source EPUB (no network access).

    EPUB2: OPF <meta name="cover" content="id">, EPUB3: properties=cover-image.
    Fallback: an image manifest entry with 'cover' in its ID or basename.
    """
    with ZipFile(epub_path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next((x for x in container.iter() if x.tag.endswith("rootfile")), None)
        if rootfile is None or not rootfile.get("full-path"):
            raise CoverError("EPUB package path not found")
        package_path = rootfile.get("full-path")
        package = ET.fromstring(archive.read(package_path))
        cover_id = ""
        for tag in package.iter():
            if tag.tag.rsplit("}", 1)[-1] == "meta":
                if tag.get("name", "").lower() == "cover":
                    cover_id = tag.get("content", "")
        manifest = []
        for tag in package.iter():
            if tag.tag.rsplit("}", 1)[-1] != "item":
                continue
            if tag.get("media-type") not in (
                "image/jpeg", "image/png", "image/gif", "image/webp",
            ):
                continue
            manifest.append(tag)
        def priority(item):
            if cover_id and item.get("id") == cover_id:
                return 0
            if "cover-image" in item.get("properties", "").split():
                return 1
            if "cover" in (item.get("id", "") + "/" + item.get("href", "")).lower():
                return 2
            return 9
        for item in sorted(manifest, key=priority):
            if priority(item) == 9:
                continue
            href = unquote(item.get("href", "").split("#", 1)[0])
            path = posixpath.normpath(posixpath.join(posixpath.dirname(package_path), href))
            if path.startswith(("../", "/")) or path not in archive.namelist():
                continue
            info = archive.getinfo(path)
            if info.file_size > MAX_IMAGE_BYTES:
                continue
            try:
                return validate_image(archive.read(path))
            except CoverError:
                continue
    return None


def write_cover(folder: Path, data: bytes, extension: str) -> str:
    if extension not in (".jpg", ".png"):
        raise CoverError("Only validated JPEG/PNG files may be saved")
    validated, actual = validate_image(data)
    if actual != extension:
        raise CoverError("Image extension does not match image content")
    folder.mkdir(parents=True, exist_ok=True)
    filename = "cover" + extension
    target = folder / filename
    target.write_bytes(validated)
    # Keep only one canonical cover file in an existing chapter folder.
    for other in ("cover.jpg", "cover.png"):
        if other != filename:
            (folder / other).unlink(missing_ok=True)
    return filename
