#!/usr/bin/env python3
"""Archive permitted FanFicFare-supported books into EPUB and chapter TXT files.

Requires the user to have permission to download and store the selected work.
"""

from __future__ import annotations

import argparse
import ipaddress
import tempfile
from uuid import uuid4
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

from bs4 import BeautifulSoup


CHAPTER_RE = re.compile(r"^\s*chap(?:ter)?\s*[#.:\-]?\s*(\d+)\b", re.IGNORECASE)

RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def parse_chapter_range(raw: str) -> tuple[int, int]:
    """Parse an inclusive 1-based chapter-position range, e.g. '10-20'."""
    match = RANGE_RE.fullmatch(raw.strip())
    if match is None:
        raise ValueError("Chapter range must be START-END, e.g. 10-20")
    start, end = map(int, match.groups())
    if start < 1 or end < start:
        raise ValueError("Chapter range must start at 1 or greater and end >= start")
    return start, end



def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:90] or "untitled-novel"


def validate_url(value: str) -> str:
    """Reject non-public destinations before handing URLs to FanFicFare.

    FanFicFare's site adapters additionally restrict supported book URLs; this
    check does not attempt to control DNS or adapter-internal redirects.
    """
    url = urlsplit(value)
    host = (url.hostname or "").lower().rstrip(".")
    if url.scheme != "https" or not host or url.username or url.password:
        raise ValueError("Use an HTTPS novel URL without embedded credentials.")
    if url.port not in (None, 443) or "." not in host:
        raise ValueError("A public HTTPS novel website URL is required.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if (address is not None or re.fullmatch(r"[0-9.]+", host)
            or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test"))
            or host.startswith("localhost.")):
        raise ValueError("IP literals and non-public hostnames are not supported.")
    return value


def _epub_package(archive: zipfile.ZipFile) -> tuple[str, ET.Element]:
    container = ET.fromstring(archive.read("META-INF/container.xml"))
    rootfile = next((n for n in container.iter() if n.tag.endswith("rootfile")), None)
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("EPUB missing package document")
    package_path = rootfile.attrib["full-path"]
    return package_path, ET.fromstring(archive.read(package_path))


def _first_text(package: ET.Element, tag: str) -> str:
    for element in package.iter():
        if element.tag.rsplit("}", 1)[-1].lower() == tag.lower():
            return (element.text or "").strip()
    return ""


def epub_chapters(epub_path: Path) -> tuple[dict, list[dict]]:
    """Read an EPUB in its declared spine order (without network access)."""
    with zipfile.ZipFile(epub_path) as archive:
        package_path, package = _epub_package(archive)
        book = {
            "title": _first_text(package, "title"),
            "author": _first_text(package, "creator"),
            "language": _first_text(package, "language"),
        }
        # Source genres and publication status are EPUB metadata, not chapter text.
        # Preserve them for both direct imports and later batch assembly.
        from tools.epub_source_metadata import source_metadata_from_package
        book.update(source_metadata_from_package(package))
        # FanFicFare and other EPUB producers often store the synopsis as
        # HTML inside dc:description. Keep plain, readable text in metadata.
        raw_description = _first_text(package, "description")
        if raw_description:
            # Decode real HTML snippets, but do not treat literal angle-bracket
            # text (for example "<unknown>") as an HTML tag and discard it.
            if re.search(r"</?(?:p|div|br|span|blockquote|ul|li|b|i|em|strong|a)\b",
                         raw_description, flags=re.IGNORECASE):
                description = BeautifulSoup(raw_description, "html.parser").get_text("\n", strip=True).strip()
            else:
                description = raw_description.strip()
            if description:
                book["description"] = description
                book["synopsis"] = description
        manifest = {}
        spine = []
        for element in package.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "item" and element.get("id") and element.get("href"):
                manifest[element.attrib["id"]] = element.attrib
            elif tag == "itemref" and element.get("idref"):
                spine.append(element.attrib["idref"])

        chapters = []
        fallback_chapters = []
        directory = posixpath.dirname(package_path)
        for item_id in spine:
            item = manifest.get(item_id, {})
            if item.get("media-type") not in ("application/xhtml+xml", "text/html"):
                continue
            path = posixpath.normpath(posixpath.join(directory, unquote(item["href"].split("#")[0])))
            if path.startswith("../") or path.startswith("/"):
                raise ValueError("Unsafe path inside EPUB")
            soup = BeautifulSoup(archive.read(path), "html.parser")
            body = soup.find("body")
            if body is None:
                continue
            heading = body.select_one(".fff_chapter_title")
            is_fanficfare = "fff_chapter" in body.get("class", []) or heading is not None
            title = heading.get_text(" ", strip=True) if heading else ""
            if not title:
                title = (soup.title.get_text(" ", strip=True) if soup.title else path)
            if heading:
                heading.decompose()
            for el in body.select("script, style"):
                el.decompose()
            paragraphs = [p.get_text(" ", strip=True) for p in body.find_all(("p", "blockquote", "pre", "li"))]
            paragraphs = [p for p in paragraphs if p]
            if paragraphs:
                body_text = "\n\n".join(paragraphs)
            else:
                body_text = "\n".join(body.stripped_strings)
            if not body_text.strip():
                # EPUB covers and other image-only spine entries are not chapters.
                continue
            chapter_data = {"title": title, "text": body_text}
            if is_fanficfare:
                chapters.append(chapter_data)
            elif len(body_text) >= 400 and not any(word in (body.get("class") or []) for word in ("nav", "toc")):
                fallback_chapters.append(chapter_data)
    if not chapters:
        # Generic EPUBs, such as public-domain Project Gutenberg books, have no
        # FanFicFare-specific chapter markers. Ignore brief title/TOC pages.
        chapters = fallback_chapters
    if not chapters:
        raise ValueError("No readable chapter pages found in EPUB")
    return book, chapters


def _export_epub_files(epub_path: Path, output_dir: Path, source_url: str | None = None, first_position: int = 1) -> dict:
    book, chapters = epub_chapters(epub_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Only files declared by a previous successful export belong to this tool.
    previous = output_dir / "chapters.json"
    owned_chapters: set[str] = set()
    if previous.exists():
        rows = json.loads(previous.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("Existing chapter manifest is invalid; refusing unsafe cleanup")
        for row in rows:
            name = row.get("file") if isinstance(row, dict) else None
            if (not isinstance(name, str) or Path(name).name != name
                    or not re.fullmatch(r"chapter_[a-zA-Z0-9_-]+\.txt", name)):
                raise ValueError("Existing chapter manifest has an unsafe filename")
            owned_chapters.add(name)
    previous_cover = ""
    previous_metadata = output_dir / "metadata.json"
    if previous_metadata.exists():
        data = json.loads(previous_metadata.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Existing metadata is invalid")
        previous_cover = data.get("cover_image", "")
    from tools.novel_covers import extract_epub_cover, write_cover
    cover = extract_epub_cover(epub_path)
    if cover:
        book["cover_image"] = write_cover(output_dir, *cover)
    if previous_cover in ("cover.jpg", "cover.png") and previous_cover != book.get("cover_image"):
        (output_dir / previous_cover).unlink(missing_ok=True)
    used_names = set()
    results = []
    next_number = 1
    for ordinal, chapter in enumerate(chapters, start=1):
        title = chapter["title"]
        match = CHAPTER_RE.match(title)
        is_prologue = "prologue" in title.lower() and ordinal == 1
        number = 0 if is_prologue else (int(match.group(1)) if match else next_number)
        next_number = max(next_number, number + 1)
        stem = f"chapter_{number:04d}" + ("_prologue" if is_prologue else "")
        filename = stem + ".txt"
        part = 2
        while filename in used_names:
            filename = f"{stem}_part{part:02d}.txt"
            part += 1
        used_names.add(filename)
        content = f"{title}\n\n{chapter['text'].strip()}\n"
        destination = output_dir / filename
        # Encode once so chapter bytes match the manifest digest on Windows too.
        destination.write_bytes(content.encode("utf-8"))
        results.append({
            "position": first_position + ordinal - 1, "chapter_number": number,
            "title": title, "file": filename,
            "word_count": len(chapter["text"].split()),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })

    for name in owned_chapters - used_names:
        (output_dir / name).unlink(missing_ok=True)
    metadata = {
        **book, "source_url": source_url, "chapter_count": len(results),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "format": "epub", "chapter_files": "UTF-8 TXT",
        "synopsis_pipeline_version": 2,  # EPUB dc:description is preserved when present
        "cover_pipeline_version": 1,  # EPUB cover image extraction supported
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "chapters.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata



def export_epub(epub_path: Path, output_dir: Path, source_url: str | None = None, first_position: int = 1) -> dict:
    """Prepare a whole export off-line and publish with rollback on rename errors.

    The previous directory is moved to a backup just before publication. If
    interrupted at that boundary, a subsequent invocation restores the backup.
    Unrelated chapter-named files are not selected for cleanup.
    """
    epub_path, output_dir = Path(epub_path), Path(output_dir)
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    backups = sorted(parent.glob(f".{output_dir.name}.backup-*"))
    if not output_dir.exists() and backups:
        if len(backups) != 1 or not backups[0].is_dir():
            raise ValueError("Ambiguous interrupted export backups; manual recovery required")
        backups[0].replace(output_dir)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}.export-", dir=parent) as temp:
        stage = Path(temp) / output_dir.name
        if output_dir.exists():
            if not output_dir.is_dir():
                raise ValueError("Export destination is not a directory")
            shutil.copytree(output_dir, stage)
        else:
            stage.mkdir()
        staged_epub = stage / "source.epub"
        if epub_path.resolve() != (output_dir / "source.epub").resolve():
            shutil.copyfile(epub_path, staged_epub)
        metadata = _export_epub_files(staged_epub, stage, source_url, first_position)
        backup = parent / f".{output_dir.name}.backup-{uuid4().hex}"
        moved_old = False
        try:
            if output_dir.exists():
                output_dir.replace(backup)
                moved_old = True
            stage.replace(output_dir)
        except OSError:
            if moved_old and backup.exists() and not output_dir.exists():
                backup.replace(output_dir)
            raise
        if moved_old:
            # A failure to clean this backup must not invalidate the published book.
            try:
                shutil.rmtree(backup)
            except OSError:
                print(f"WARNING: Previous export backup retained: {backup}", file=sys.stderr)
        return metadata

def run_fanficfare(url: str, book_dir: Path, list_only: bool, start: int | None, end: int | None, timeout_minutes: int = 120) -> None:
    executable = shutil.which("fanficfare")
    if not executable:
        raise RuntimeError("FanFicFare executable not found. Install requirements.txt first.")
    if list_only:
        args = [executable, "--non-interactive", "--meta-only", "--json-meta", "--no-output", url]
        subprocess.run(args, check=True, timeout=timeout_minutes * 60)
        return

    # FanFicFare --progressbar prints dots per network fetch, not per chapter.
    # Run its CLI through the chapter-completion callback adapter.
    runner = Path(__file__).resolve().with_name("fff_progress_runner.py")
    args = [sys.executable, str(runner), "--non-interactive", "-f", "epub", "-o", "output_filename=source.epub"]
    if start is not None:
        args += ["--begin", str(start)]
    if end is not None:
        args += ["--end", str(end)]
    args.append(url)
    print("Running FanFicFare (chapter count and percentage will be displayed)...", flush=True)
    subprocess.run(args, cwd=book_dir, check=True, timeout=timeout_minutes * 60)


def _same_file_content(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    def digest(path: Path) -> str:
        result = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                result.update(chunk)
        return result.hexdigest()
    return digest(a) == digest(b)


def _completed_chapters(output_dir: Path) -> int:
    rows = json.loads((output_dir / "chapters.json").read_text(encoding="utf-8"))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Story URL supported by FanFicFare")
    parser.add_argument("--import-epub", type=Path, help="Import an existing EPUB instead of downloading")
    parser.add_argument("--confirm-rights", action="store_true", help="Confirm you have permission to download/store this work")
    parser.add_argument("--list-only", action="store_true", help="Discover metadata and chapter links only")
    parser.add_argument("--chapter-range", "--range", help="Inclusive chapter index positions: START-END")
    parser.add_argument("--begin-chapter", type=int, help="First chapter position in FanFicFare's index (1-based)")
    parser.add_argument("--end-chapter", type=int, help="Last chapter position in FanFicFare's index (inclusive)")
    parser.add_argument("--output-dir", type=Path, default=Path("downloads"))
    parser.add_argument("--slug", help="Optional folder name for the novel")
    parser.add_argument("--overwrite", action="store_true", help="Replace a verified same-source download, or explicitly replace a local EPUB import")
    parser.add_argument("--expected-chapters", type=int, help="Optional expected number of chapters for unrestricted downloads")
    parser.add_argument("--timeout-minutes", type=int, default=120, help="Total download runtime limit (default 120)")
    parser.add_argument("--self-test", action="store_true", help="Run FanFicFare built-in 9-chapter test story without network")
    options = parser.parse_args(argv)

    if sum((bool(options.url), bool(options.import_epub), options.self_test)) != 1:
        parser.error("Supply exactly one of URL, --import-epub or --self-test")
    if options.timeout_minutes < 1:
        parser.error("--timeout-minutes must be positive")
    if options.expected_chapters is not None and options.expected_chapters < 1:
        parser.error("--expected-chapters must be positive")
    if options.url and not options.confirm_rights:
        parser.error("Confirm that you have the rights and permission to archive the work with --confirm-rights")
    if options.chapter_range:
        if options.begin_chapter is not None or options.end_chapter is not None:
            parser.error("Specify either --chapter-range or --begin-chapter/--end-chapter")
        try:
            options.begin_chapter, options.end_chapter = parse_chapter_range(options.chapter_range)
        except ValueError as exc:
            parser.error(str(exc))
    if options.import_epub and (options.begin_chapter is not None or options.end_chapter is not None):
        parser.error("Chapter ranges apply to URL downloads and --self-test, not EPUB import")
    if options.list_only and (options.import_epub or options.begin_chapter or options.end_chapter):
        parser.error("--list-only is for discovering a full novel URL")
    if any(n is not None and n < 1 for n in (options.begin_chapter, options.end_chapter)):
        parser.error("Chapter positions must be positive")
    if options.begin_chapter and options.end_chapter and options.end_chapter < options.begin_chapter:
        parser.error("--end-chapter must not precede --begin-chapter")

    pending_download: Path | None = None
    try:
        if options.url or options.self_test:
            url = validate_url(options.url) if options.url else "http://test1.com?sid=123"
            if options.list_only:
                run_fanficfare(url, Path.cwd(), True, None, None, options.timeout_minutes)
                return 0
            # A readable prefix alone is not a novel identity: different sites
            # routinely reuse the same title or terminal URL path.
            base = ("fanficfare-smoke-test" if options.self_test else
                    slugify(Path(urlsplit(url).path).stem) + "-" +
                    hashlib.sha256(url.encode("utf-8")).hexdigest()[:12])
            # Separate output names prevent a new batch reusing an earlier EPUB.
            if options.begin_chapter is not None or options.end_chapter is not None:
                first = str(options.begin_chapter or 1).zfill(4)
                last = str(options.end_chapter).zfill(4) if options.end_chapter is not None else "end"
                base = f"{base}-chapters-{first}-{last}"
            name = options.slug or base
            book_dir = options.output_dir / slugify(name)
            epub = book_dir / "source.epub"
            prior_metadata = book_dir / "metadata.json"
            if epub.is_file():
                if prior_metadata.is_file():
                    prior_url = json.loads(prior_metadata.read_text(encoding="utf-8")).get("source_url")
                    if prior_url != url:
                        raise ValueError(
                            f"Existing EPUB belongs to {prior_url!r}, not {url!r}; "
                            "choose a different --slug to protect both novels")
                elif not options.overwrite:
                    raise ValueError(
                        "Existing EPUB has no verified source identity; use --overwrite to re-download")
            book_dir.mkdir(parents=True, exist_ok=True)
            if options.overwrite and epub.is_file():
                # Redownload outside the published directory, so failed refreshes
                # leave the last complete novel untouched.
                pending_download = Path(tempfile.mkdtemp(
                    prefix=f".{book_dir.name}.redownload-", dir=book_dir.parent))
                run_fanficfare(url, pending_download, False, options.begin_chapter,
                               options.end_chapter, options.timeout_minutes)
                epub = pending_download / "source.epub"
            elif not epub.is_file():
                run_fanficfare(url, book_dir.resolve(), False, options.begin_chapter, options.end_chapter, options.timeout_minutes)
            else:
                print(f"Using existing EPUB: {epub}. Use --overwrite to fetch anew.", flush=True)
        else:
            url = None
            input_epub = options.import_epub.resolve()
            if not input_epub.is_file():
                raise FileNotFoundError(input_epub)
            book, _ = epub_chapters(input_epub)
            book_dir = options.output_dir / slugify(options.slug or book["title"] or input_epub.stem)
            epub = book_dir / "source.epub"
            if epub.is_file() and input_epub != epub.resolve():
                if not options.overwrite and not _same_file_content(input_epub, epub):
                    raise ValueError(
                        "Different EPUB already exists for this title; "
                        "use --slug to keep both or --overwrite to replace intentionally")
            # export_epub publishes the incoming EPUB together with its chapter
            # representation; never replace the live source before validation.
            epub = input_epub

        if not epub.is_file():
            raise RuntimeError("FanFicFare finished without creating source.epub")
        first_position = (options.begin_chapter or 1) if (options.url or options.self_test) else 1
        # Fail before publication if the downloaded EPUB is incomplete.
        _, pending_chapters = epub_chapters(epub)
        expected_range = (options.end_chapter - options.begin_chapter + 1
                          if options.begin_chapter is not None and options.end_chapter is not None
                          else None)
        if expected_range is not None and len(pending_chapters) != expected_range:
            raise ValueError(f"Expected {expected_range} chapters in range, found {len(pending_chapters)}")
        if options.expected_chapters is not None and len(pending_chapters) != options.expected_chapters:
            raise ValueError(f"Expected {options.expected_chapters} chapters, found {len(pending_chapters)}")
        meta = export_epub(epub, book_dir, url, first_position=first_position)
        if options.begin_chapter is not None and options.end_chapter is not None:
            expected = options.end_chapter - options.begin_chapter + 1
            if meta["chapter_count"] != expected:
                raise ValueError(f"Expected {expected} chapters in range but exported {meta['chapter_count']}; checkpoints retained")
        if options.expected_chapters is not None and meta["chapter_count"] != options.expected_chapters:
            raise ValueError(f"Expected {options.expected_chapters} chapters, exported {meta['chapter_count']}")
        if (options.url and options.begin_chapter is None and options.end_chapter is None
                and options.expected_chapters is None):
            print("WARNING: No authoritative expected chapter count; this direct download "
                  "cannot establish full-book completeness. Use the bounded batch workflow "
                  "for verified full novels.", flush=True)
        checkpoint_dir = book_dir / "chapters_in_progress"
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)
        print(f"Saved {meta['chapter_count']} chapters, metadata and EPUB to: {book_dir.resolve()}", flush=True)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if pending_download is not None:
            shutil.rmtree(pending_download, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
