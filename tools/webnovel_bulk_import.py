#!/usr/bin/env python3
"""Offline bulk conversion of user-saved, authorised WebNovel chapters.

Reads local .html/.htm/.txt files only. Does not contact WebNovel, use
browser cookies, or change the existing two-chapter or NovelFull tools.
Supports consecutively numbered chapters, a selected range, and resumable
local extraction with validated source/output hashes.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import sys
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from tools.webnovel_saved_pages import SavedPageError, read_saved_chapter, SUPPORTED_SUFFIXES

MAX_CHAPTERS = 10000
MAX_BODY_CHARS = 500000
STATE_NAME = ".webnovel-import-state.json"
CHAPTER_RE = re.compile(r"\b(?:chapter|chap|ch)\s*[#:_\-. ]*0*(\d+)(?!\d)", re.IGNORECASE)
TRAILING_SOURCE = re.compile(r"\s*[-|]\s*WebNovel\s*$", re.IGNORECASE)


class BulkImportError(ValueError):
    """Invalid import plan, input, or saved output."""


def parse_chapter_name(path: Path) -> tuple[int, str]:
    stem = path.stem
    matches = list(CHAPTER_RE.finditer(stem))
    if not matches:
        raise BulkImportError(f"No chapter number in filename: {path.name}")
    numbers = {int(match.group(1)) for match in matches}
    if len(numbers) != 1 or next(iter(numbers)) < 1:
        raise BulkImportError(f"Conflicting or invalid chapter numbers: {path.name}")
    number = next(iter(numbers))
    tail = TRAILING_SOURCE.sub("", stem[matches[-1].end():]).strip(" -_:|\t")
    # Browser HTML names often repeat 'Chapter 2 - Chapter 2_ Title'.
    title = f"Chapter {number}: {tail}" if tail else f"Chapter {number}"
    if len(title) > 240:
        raise BulkImportError(f"Chapter title is too long: {path.name}")
    return number, title


def parse_range(raw: str | None) -> tuple[int, int] | None:
    if raw is None:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", raw)
    if not match:
        raise BulkImportError("Chapter range must be START-END, for example 1-50")
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1 or end < start or end - start + 1 > MAX_CHAPTERS:
        raise BulkImportError("Chapter range must be positive, ordered and at most 10,000 chapters")
    return start, end


def plan_import(input_dir: Path, chapter_range: str | None = None) -> list[dict]:
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise BulkImportError(f"Input directory does not exist: {input_dir}")
    available: dict[int, dict] = {}
    for path in sorted(input_dir.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        number, title = parse_chapter_name(path)
        if number in available:
            raise BulkImportError(
                f"Duplicate chapter {number}: {available[number]['file']} and {path.name}"
            )
        available[number] = {"position": number, "title": title, "file": path.name}
    if not available:
        raise BulkImportError("No numbered .html/.htm/.txt chapter files found")
    selected_range = parse_range(chapter_range)
    start, end = selected_range or (min(available), max(available))
    if end - start + 1 > MAX_CHAPTERS:
        raise BulkImportError("Import exceeds the 10,000 chapter safety limit")
    missing = [n for n in range(start, end + 1) if n not in available]
    if missing:
        sample = ", ".join(str(n) for n in missing[:12])
        suffix = " ..." if len(missing) > 12 else ""
        raise BulkImportError(f"Missing {len(missing)} chapter(s): {sample}{suffix}")
    return [available[n] for n in range(start, end + 1)]


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_state(path: Path, identity: dict, resume: bool) -> dict:
    if resume:
        if not path.is_file():
            raise BulkImportError("No previous import state found; omit --resume for a new run")
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise BulkImportError("Import state is unreadable or damaged") from exc
        for field, value in identity.items():
            if state.get(field) != value:
                raise BulkImportError(f"Import state mismatch for {field}; use a fresh output directory")
        completed = state.get("completed")
        if not isinstance(completed, dict):
            raise BulkImportError("Import state has an invalid completed-chapter list")
        return state
    return {**identity, "completed": {}}


def _output_file(number: int) -> str:
    return f"chapter-{number:06d}.txt"


def _validate_resumed_chapters(state: dict, entries: list[dict], input_dir: Path, output_dir: Path) -> None:
    by_number = {str(item["position"]): item for item in entries}
    for number, previous in state["completed"].items():
        if number not in by_number or not isinstance(previous, dict):
            raise BulkImportError("Import state refers to an unknown chapter")
        entry = by_number[number]
        source = input_dir / entry["file"]
        output = output_dir / _output_file(int(number))
        if not source.is_file() or _hash_file(source) != previous.get("source_sha256"):
            raise BulkImportError(f"Chapter {number} source changed; start a fresh import")
        if not output.is_file() or _hash_file(output) != previous.get("output_sha256"):
            raise BulkImportError(f"Chapter {number} output changed; start a fresh import")


def _generate_outputs(output_dir: Path, title: str, author: str, entries: list[dict]) -> dict:
    manifest = [{"position": e["position"], "title": e["title"],
                 "file": _output_file(e["position"]), "source_file": e["file"]}
                for e in entries]
    metadata = {"title": title, "author": author, "source": "user-supplied-authorised",
                "chapter_count": len(entries), "chapters": manifest}
    text_path = output_dir / "book.txt"
    text_tmp = output_dir / "book.txt.tmp"
    epub_path = output_dir / "book.epub"
    epub_tmp = output_dir / "book.epub.tmp"
    uid = str(uuid5(NAMESPACE_URL, title + "\n" + author))
    nav = "".join(
        f'<navPoint id="nav{i}" playOrder="{i}"><navLabel><text>{escape(e["title"])}</text></navLabel>'
        f'<content src="chapter-{e["position"]:06d}.xhtml"/></navPoint>'
        for i, e in enumerate(entries, 1)
    )
    items = "".join(
        f'<item id="ch{i}" href="chapter-{e["position"]:06d}.xhtml" media-type="application/xhtml+xml"/>'
        for i, e in enumerate(entries, 1)
    )
    spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(1, len(entries) + 1))
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="bookid">urn:uuid:{uid}</dc:identifier>'
        f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
        '<dc:language>en</dc:language></metadata>'
        '<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        f'{items}</manifest><spine toc="ncx">{spine}</spine></package>'
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="urn:uuid:{uid}"/></head>'
        f'<docTitle><text>{escape(title)}</text></docTitle><navMap>{nav}</navMap></ncx>'
    )
    try:
        with text_tmp.open("w", encoding="utf-8", newline="\n") as combined, ZipFile(epub_tmp, "w") as archive:
            combined.write(f"{title}\n{author}\n\n")
            archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
            archive.writestr("META-INF/container.xml",
                '<?xml version="1.0" encoding="utf-8"?>'
                '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                '</rootfiles></container>', compress_type=ZIP_DEFLATED)
            archive.writestr("OEBPS/content.opf", opf, compress_type=ZIP_DEFLATED)
            archive.writestr("OEBPS/toc.ncx", ncx, compress_type=ZIP_DEFLATED)
            for e in entries:
                full = (output_dir / _output_file(e["position"])).read_text(encoding="utf-8")
                combined.write(full.rstrip() + "\n\n")
                # The saved TXT begins with the chapter title and an empty line.
                _, separator, body = full.partition("\n\n")
                if not separator:
                    raise BulkImportError(f"Chapter {e['position']} saved TXT is malformed")
                paragraphs = "".join(
                    f"<p>{escape(p.strip()).replace(chr(10), '<br/>')}</p>"
                    for p in re.split(r"\n\s*\n", body.strip()) if p.strip()
                )
                xhtml = (
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                    f'<title>{escape(e["title"])}</title></head><body>'
                    f'<h1>{escape(e["title"])}</h1>{paragraphs}</body></html>'
                )
                archive.writestr(f'OEBPS/chapter-{e["position"]:06d}.xhtml', xhtml,
                                 compress_type=ZIP_DEFLATED)
        with ZipFile(epub_tmp) as check:
            if check.testzip() is not None:
                raise BulkImportError("Generated EPUB archive failed validation")
        text_tmp.replace(text_path)
        epub_tmp.replace(epub_path)
        _write_text_atomic(output_dir / "metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    finally:
        text_tmp.unlink(missing_ok=True)
        epub_tmp.unlink(missing_ok=True)
    return metadata


def bulk_import(input_dir, output_dir, title, author, *, chapter_range=None,
                confirm_rights=False, resume=False, dry_run=False, progress=print):
    """Import a folder of individually saved local chapters; never uses networking."""
    if not confirm_rights:
        raise BulkImportError("Explicit --confirm-rights is required")
    for value, field in [(title, "title"), (author, "author")]:
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 240:
            raise BulkImportError(f"{field} must be 1-240 characters")
        if any(ord(ch) < 32 for ch in value):
            raise BulkImportError(f"{field} contains invalid characters")
    title, author = title.strip(), author.strip()
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if input_dir == output_dir:
        raise BulkImportError("Output directory must differ from the input directory")
    entries = plan_import(input_dir, chapter_range)
    if dry_run:
        return {"chapter_count": len(entries), "first_chapter": entries[0]["position"],
                "last_chapter": entries[-1]["position"], "chapters": entries}
    if resume:
        if not output_dir.is_dir():
            raise BulkImportError("Output directory for --resume does not exist")
    elif output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise BulkImportError("Output directory must be empty; use --resume to continue a previous import")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
    identity = {"schema_version": 1, "title": title, "author": author,
                "input_dir": str(input_dir), "entries": entries}
    state_path = output_dir / STATE_NAME
    state = _load_state(state_path, identity, resume)
    if resume:
        _validate_resumed_chapters(state, entries, input_dir, output_dir)
    else:
        _write_text_atomic(state_path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    total = len(entries)
    for i, entry in enumerate(entries, 1):
        number = entry["position"]
        if str(number) in state["completed"]:
            progress(f"[{i}/{total}] {i * 100 // total}% reused Chapter {number}")
            continue
        source = input_dir / entry["file"]
        try:
            text = read_saved_chapter(source, entry["title"])
        except SavedPageError as exc:
            raise BulkImportError(f"Chapter {number} could not be imported: {exc}") from exc
        if not 100 <= len(text) <= MAX_BODY_CHARS:
            raise BulkImportError(f"Chapter {number} has an invalid text length: {len(text)}")
        saved = f'{entry["title"]}\n\n{text}\n'
        path = output_dir / _output_file(number)
        _write_text_atomic(path, saved)
        state["completed"][str(number)] = {"source_sha256": _hash_file(source),
                                             "output_sha256": _hash_file(path)}
        _write_text_atomic(state_path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        progress(f"[{i}/{total}] {i * 100 // total}% imported Chapter {number}")
    result = _generate_outputs(output_dir, title, author, entries)
    progress(f"EPUB and TXT complete: {total} chapter(s)")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--book-title", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--chapter-range", help="Optional inclusive range, e.g. 1-50")
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Reuse validated chapters from interrupted import")
    parser.add_argument("--dry-run", action="store_true", help="Validate names and ordering without creating files")
    args = parser.parse_args(argv)
    try:
        result = bulk_import(
            args.input_dir, args.output_dir, args.book_title, args.author,
            chapter_range=args.chapter_range, confirm_rights=args.confirm_rights,
            resume=args.resume, dry_run=args.dry_run,
        )
        print(json.dumps(result if args.dry_run else {
            "title": result["title"], "author": result["author"],
            "chapter_count": result["chapter_count"],
            "first_chapter": result["chapters"][0]["position"],
            "last_chapter": result["chapters"][-1]["position"],
            "output_dir": str(args.output_dir),
            "epub": "book.epub", "text": "book.txt"
        }, indent=2, ensure_ascii=False))
        return 0
    except (BulkImportError, OSError, ValueError) as exc:
        print(f"WebNovel bulk import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
