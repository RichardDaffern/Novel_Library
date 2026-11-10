#!/usr/bin/env python3
"""Repair missing synopsis metadata in existing novel ZIPs without re-downloading chapters.

Repairs are validated in a temporary ZIP, then atomically replace the original.
The original is untouched if extraction, rewriting or validation fails.
May use a provided synopsis or the ordinary public NovelFull book page.
No login, proxies, CAPTCHAs, paywall bypass, or automatic retries.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

from bs4 import BeautifulSoup

DC = "http://purl.org/dc/elements/1.1/"
OPF = "http://www.idpf.org/2007/opf"
MAX_HTML = 2 * 1024 * 1024
ET.register_namespace("", OPF)
ET.register_namespace("dc", DC)


class SynopsisError(ValueError):
    """Unsafe archive, missing synopsis or unsuitable input."""


def clean_description(value: str) -> str:
    if not isinstance(value, str):
        raise SynopsisError("Synopsis must be text")
    # Known HTML description containers may use paragraphs. Preserve plain text
    # with arbitrary angle brackets rather than mistakenly treating it as HTML.
    has_markup = re.search(r"</?(?:p|div|br|span|blockquote|ul|li|b|i|em|strong|a)\b",
                           value, re.IGNORECASE)
    text = BeautifulSoup(value, "html.parser").get_text("\n", strip=True) if has_markup else value
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(text) < 25 or len(text) > 10000:
        raise SynopsisError("Synopsis must contain 25-10,000 readable characters")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise SynopsisError("Synopsis contains control characters")
    return text


def public_novelfull_synopsis(url: str) -> str:
    """Only one ordinary public novel information page, never a chapter page."""
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "novelfull.com"
            or parts.port is not None or parts.username or parts.password
            or not re.fullmatch(r"/[a-z0-9_-]+\.html", parts.path)
            or parts.query or parts.fragment):
        raise SynopsisError("Automatic synopsis lookup currently supports NovelFull URLs only")
    try:
        request = Request(url, headers={"User-Agent": "NovelLibrarySynopsisRepair/1.0"})
        with urlopen(request, timeout=20) as response:
            if response.headers.get("cf-mitigated", "").lower() == "challenge":
                raise SynopsisError("Source returned an access challenge; stopped")
            if response.status != 200:
                raise SynopsisError(f"Source returned HTTP {response.status}")
            data = response.read(MAX_HTML + 1)
        if len(data) > MAX_HTML:
            raise SynopsisError("Novel metadata page exceeds 2 MiB")
    except (HTTPError, URLError) as exc:
        raise SynopsisError(f"Source metadata unavailable: {exc}") from exc
    soup = BeautifulSoup(data, "html.parser")
    if soup.title and "just a moment" in soup.title.get_text(" ", strip=True).lower():
        raise SynopsisError("Source access challenge; stopped")
    node = soup.select_one("div.desc-text")
    if node is None:
        raise SynopsisError("No description found on the public NovelFull book page")
    return clean_description(str(node))


def read_epub_description(epub: bytes) -> tuple[str, str, ET.Element, ET.Element]:
    with ZipFile(BytesIO(epub)) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next((tag for tag in container.iter() if tag.tag.endswith("rootfile")), None)
        if rootfile is None or not rootfile.get("full-path"):
            raise SynopsisError("EPUB is missing its package document")
        path = rootfile.attrib["full-path"]
        if path.startswith("/") or ".." in Path(path).parts or path not in archive.namelist():
            raise SynopsisError("Unsafe EPUB package path")
        package = ET.fromstring(archive.read(path))
        metadata = next((node for node in package.iter() if node.tag.endswith("metadata")), None)
        if metadata is None:
            raise SynopsisError("EPUB package lacks metadata")
        desc = metadata.find(f"{{{DC}}}description")
        value = desc.text.strip() if desc is not None and desc.text else ""
        return path, value, package, metadata


def patch_epub(epub: bytes, synopsis: str) -> bytes:
    package_path, _, package, metadata = read_epub_description(epub)
    elem = metadata.find(f"{{{DC}}}description")
    if elem is None:
        elem = ET.SubElement(metadata, f"{{{DC}}}description")
    elem.text = synopsis
    new_opf = ET.tostring(package, encoding="utf-8", xml_declaration=True)
    with ZipFile(BytesIO(epub)) as source:
        result = BytesIO()
        with ZipFile(result, "w") as out:
            for entry in source.infolist():
                data = new_opf if entry.filename == package_path else source.read(entry)
                out.writestr(entry, data)
        new_bytes = result.getvalue()
    if read_epub_description(new_bytes)[1] != synopsis:
        raise SynopsisError("Repaired EPUB failed synopsis verification")
    return new_bytes


def archive_info(path: Path) -> tuple[str, str, dict, bytes, str]:
    with ZipFile(path) as source:
        names = source.namelist()
        meta_files = [name for name in names if name.endswith("/metadata.json")]
        epub_files = [name for name in names if name.endswith("/source.epub")]
        if len(meta_files) != 1 or len(epub_files) != 1:
            raise SynopsisError("Expected one novel folder with metadata.json and source.epub")
        meta_path, epub_path = meta_files[0], epub_files[0]
        if meta_path.rsplit("/", 1)[0] != epub_path.rsplit("/", 1)[0]:
            raise SynopsisError("Metadata and EPUB belong to different novel folders")
        metadata = json.loads(source.read(meta_path).decode("utf-8"))
        if not isinstance(metadata, dict) or not metadata.get("source_url"):
            raise SynopsisError("Missing source_url in archive metadata")
        epub_bytes = source.read(epub_path)
        return meta_path, epub_path, metadata, epub_bytes, read_epub_description(epub_bytes)[1]


def _verify_repair(original_path: Path, candidate_path: Path, meta_path: str,
                   epub_path: str, expected_meta: dict, synopsis: str) -> None:
    """Check that the replacement changes *only* synopsis metadata.

    Read every archive member, not just its ZIP central directory. That
    validates CRCs and ensures all chapter bytes and manifests are identical.
    """
    with ZipFile(original_path) as original, ZipFile(candidate_path) as candidate:
        if original.namelist() != candidate.namelist():
            raise SynopsisError("Repaired ZIP changed its contents list")
        if original.testzip() is not None or candidate.testzip() is not None:
            raise SynopsisError("Original or repaired ZIP failed CRC verification")
        saved_meta = json.loads(candidate.read(meta_path))
        if saved_meta != expected_meta:
            raise SynopsisError("Repaired metadata differs beyond the synopsis fields")
        with ZipFile(BytesIO(original.read(epub_path))) as old_epub, \
                ZipFile(BytesIO(candidate.read(epub_path))) as new_epub:
            if old_epub.namelist() != new_epub.namelist():
                raise SynopsisError("Repair changed EPUB's file list")
            opf_path = read_epub_description(new_epub.fp.getvalue() if isinstance(
                new_epub.fp, BytesIO) else candidate.read(epub_path))[0]
            if read_epub_description(candidate.read(epub_path))[1] != synopsis:
                raise SynopsisError("Repaired EPUB synopsis verification failed")
            for name in old_epub.namelist():
                if name != opf_path and old_epub.read(name) != new_epub.read(name):
                    raise SynopsisError(f"Repair altered EPUB member {name}")
        for name in original.namelist():
            if name not in (meta_path, epub_path):
                # Compare in bounded chunks to avoid loading hundreds of chapters
                # into memory when repairing large novels.
                with original.open(name) as before, candidate.open(name) as after:
                    while True:
                        old_chunk = before.read(1024 * 1024)
                        new_chunk = after.read(1024 * 1024)
                        if old_chunk != new_chunk:
                            raise SynopsisError(f"Repair altered archive member {name}")
                        if not old_chunk:
                            break


def repair(path: Path, output_dir: Path | None = None, *, provided="",
           fetcher=public_novelfull_synopsis) -> str:
    """Validate a temporary ZIP and atomically replace the original by default.

    Supplying an explicit output_dir retains the previous copy-mode behaviour,
    but the default --apply operation never creates a duplicate output folder.
    """
    path = Path(path)
    original_stat = path.stat()
    meta_path, epub_path, metadata, epub_bytes, old_epub = archive_info(path)
    existing = metadata.get("description") or metadata.get("synopsis") or old_epub
    if existing and not provided:
        synopsis = clean_description(existing)
        if (metadata.get("description") == synopsis and metadata.get("synopsis") == synopsis
                and old_epub == synopsis):
            return "synopsis already complete"
    else:
        synopsis = clean_description(provided or fetcher(metadata["source_url"]))

    new_meta = dict(metadata)
    new_meta["description"] = synopsis
    new_meta["synopsis"] = synopsis
    new_epub = patch_epub(epub_bytes, synopsis)

    output = (Path(output_dir) / path.name) if output_dir is not None else path
    replacing_original = output.resolve() == path.resolve()
    if not replacing_original and output.exists():
        return "repaired output already exists"
    output.parent.mkdir(parents=True, exist_ok=True)
    # Same-directory staging is required for an atomic rename on Windows/NTFS.
    with tempfile.NamedTemporaryFile(prefix=".synopsis-", suffix=".zip",
                                     dir=output.parent, delete=False) as tmp:
        working = Path(tmp.name)
    try:
        with ZipFile(path) as source, ZipFile(working, "w") as destination:
            for entry in source.infolist():
                if entry.filename == meta_path:
                    data = (json.dumps(new_meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                    destination.writestr(entry, data)
                elif entry.filename == epub_path:
                    destination.writestr(entry, new_epub)
                else:
                    with source.open(entry) as original, destination.open(entry, "w") as copied:
                        shutil.copyfileobj(original, copied, length=1024 * 1024)

        _verify_repair(path, working, meta_path, epub_path, new_meta, synopsis)

        # Flush the fully validated replacement to disk before the swap.
        with working.open("r+b") as file:
            file.flush()
            os.fsync(file.fileno())
        if replacing_original:
            current_stat = path.stat()
            if (current_stat.st_size, current_stat.st_mtime_ns) != (
                    original_stat.st_size, original_stat.st_mtime_ns):
                raise SynopsisError(
                    "Original ZIP changed during repair; not replacing it"
                )
            shutil.copymode(path, working)
        working.replace(output)  # atomic on the same filesystem
    finally:
        working.unlink(missing_ok=True)
    return f"replaced original {output}" if replacing_original else f"saved {output}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip", type=Path, help="One existing novel ZIP")
    source.add_argument("--directory", type=Path, help="Folder of existing novel ZIPs")
    parser.add_argument("--output-dir", type=Path, help="Optional copy-only folder; by default replace each original ZIP in place")
    parser.add_argument("--description", help="Custom synopsis for one ZIP, without network")
    parser.add_argument("--description-file", type=Path, help="UTF-8 text synopsis for one ZIP")
    parser.add_argument("--apply", action="store_true", help="Atomically replace original ZIPs after validation (dry-run by default)")
    args = parser.parse_args(argv)
    if args.description and args.description_file:
        parser.error("Use --description or --description-file, not both")
    if (args.description or args.description_file) and args.directory:
        parser.error("A custom description applies only to a single --zip")
    provided = (args.description_file.read_text(encoding="utf-8")
                if args.description_file else args.description or "")
    inputs = [args.zip] if args.zip else sorted(args.directory.glob("*.zip"))
    if not inputs:
        parser.error("No novel ZIPs found")
    output_dir = args.output_dir
    errors = 0
    for index, path in enumerate(inputs):
        try:
            if not path.is_file():
                raise SynopsisError(f"Missing ZIP: {path}")
            if args.apply:
                status = repair(path, output_dir, provided=provided)
            else:
                _, _, metadata, _, current = archive_info(path)
                status = ("synopsis present" if
                          (metadata.get("description") or metadata.get("synopsis") or current)
                          else "missing synopsis")
            print(f"{path.name}: {status}", flush=True)
            if args.apply and len(inputs) > 1 and index != len(inputs) - 1:
                time.sleep(1)
        except (OSError, ValueError, BadZipFile, ET.ParseError) as exc:
            errors += 1
            print(f"{path.name}: ERROR {exc}", file=sys.stderr, flush=True)
    print(f"Checked {len(inputs)} ZIPs, {errors} errors", flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
