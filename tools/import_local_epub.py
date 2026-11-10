#!/usr/bin/env python3
"""Convert an already-authorised local EPUB to a Novel_Library reader ZIP.

This tool never makes network requests. It is useful for author-provided EPUBs
(including Royal Road's author EPUB export) or other EPUBs you are permitted
to save. WTR-Lab's website does NOT itself authorise downloading novels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from zipfile import ZipFile, BadZipFile, ZIP_DEFLATED

from novel_downloader import epub_chapters, export_epub, slugify
from tools.source_feasibility import SourceProbeError, validate_book_url

MAX_INPUT_EPUB = 300 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 750 * 1024 * 1024
MAX_UNCOMPRESSED_MEMBER = 30 * 1024 * 1024
MAX_CHAPTERS = 20000


class LocalImportError(ValueError):
    """Unsafe EPUB, unsupported provenance or unsuccessful packaging."""


def inspect_local_epub(path: Path) -> tuple[dict, int]:
    if not path.is_file() or path.suffix.lower() != ".epub":
        raise LocalImportError("Supply an existing .epub file")
    size = path.stat().st_size
    if not size or size > MAX_INPUT_EPUB:
        raise LocalImportError("Input EPUB is empty or exceeds the 300 MiB limit")
    try:
        with ZipFile(path) as archive:
            items = archive.infolist()
            if len(items) > MAX_CHAPTERS + 500:
                raise LocalImportError("EPUB contains too many internal files")
            if any(
                info.file_size > MAX_UNCOMPRESSED_MEMBER
                for info in items
            ):
                raise LocalImportError("An EPUB member exceeds the 30 MiB safety limit")
            if sum(info.file_size for info in items) > MAX_TOTAL_UNCOMPRESSED:
                raise LocalImportError("EPUB expands beyond 750 MiB")
            if archive.testzip() is not None:
                raise LocalImportError("Source EPUB has a CRC error")
        metadata, chapters = epub_chapters(path)
        if not metadata.get("title") or not chapters or len(chapters) > MAX_CHAPTERS:
            raise LocalImportError("EPUB has no usable title or readable chapters")
    except (BadZipFile, KeyError, OSError) as exc:
        raise LocalImportError("Invalid EPUB input") from exc
    return metadata, len(chapters)


def import_epub_to_zip(epub: Path, output_dir: Path, source_url: str, *,
                       confirm_rights: bool = False, replace: bool = False) -> Path:
    if not confirm_rights:
        raise LocalImportError("Confirm that you are permitted to archive this EPUB")
    try:
        site, canonical_url = validate_book_url(source_url)
    except SourceProbeError as exc:
        raise LocalImportError(str(exc)) from exc
    if site not in ("WTRLab", "RoyalRoad"):
        raise LocalImportError("Only WTR-Lab and Royal Road source URLs are accepted here")
    epub = Path(epub)
    metadata, chapter_count = inspect_local_epub(epub)
    title = str(metadata["title"]).strip()
    book_slug = slugify(title)
    if not book_slug or book_slug in (".", ".."):
        raise LocalImportError("EPUB has an invalid title for folder naming")
    identity = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:12]
    output_dir = Path(output_dir)
    output = output_dir / f"novel-{identity}.zip"
    if output.exists() and not replace:
        raise LocalImportError("Output ZIP already exists; use --replace to overwrite it")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Everything is staged and verified before the final atomic rename.
    with tempfile.TemporaryDirectory(prefix="local-epub-import-") as temp:
        temp_root = Path(temp)
        book = temp_root / book_slug
        book.mkdir()
        shutil.copyfile(epub, book / "source.epub")
        saved = export_epub(book / "source.epub", book, canonical_url)
        if saved["chapter_count"] != chapter_count:
            raise LocalImportError("Chapter count changed during EPUB conversion")
        with tempfile.NamedTemporaryFile(prefix=".novel-", suffix=".zip",
                                         dir=output_dir, delete=False) as file:
            staged = Path(file.name)
        try:
            expected = [
                "metadata.json", "chapters.json", "source.epub",
                *[row["file"] for row in json.loads(
                    (book / "chapters.json").read_text(encoding="utf-8")
                )],
            ]
            if saved.get("cover_image"):
                expected.append(saved["cover_image"])
            if len(set(expected)) != len(expected):
                raise LocalImportError("Duplicate filename in novel archive")
            with ZipFile(staged, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                for relative in expected:
                    candidate = book / relative
                    if not candidate.is_file() or candidate.parent != book:
                        raise LocalImportError(f"Missing or unsafe book member: {relative}")
                    archive.write(candidate, arcname=f"{book_slug}/{relative}")
            with ZipFile(staged) as check:
                if check.testzip() is not None:
                    raise LocalImportError("Final novel ZIP failed CRC verification")
                if check.namelist() != [f"{book_slug}/{name}" for name in expected]:
                    raise LocalImportError("Final archive files do not match the manifest")
                output_metadata = json.loads(check.read(f"{book_slug}/metadata.json"))
                rows = json.loads(check.read(f"{book_slug}/chapters.json"))
                if (output_metadata["source_url"] != canonical_url or
                        output_metadata["chapter_count"] != chapter_count or
                        len(rows) != chapter_count):
                    raise LocalImportError("Final ZIP metadata failed validation")
                for row in rows:
                    data = check.read(f"{book_slug}/{row['file']}")
                    if hashlib.sha256(data).hexdigest() != row["sha256"]:
                        raise LocalImportError(f"Chapter failed SHA-256 check: {row['file']}")
                if saved.get("cover_image"):
                    from tools.novel_covers import validate_image
                    cover = check.read(f"{book_slug}/{saved['cover_image']}")
                    _, extension = validate_image(cover)
                    if extension != Path(saved["cover_image"]).suffix:
                        raise LocalImportError("Cover image type mismatch")
            # Ensure the final validated ZIP exists durably before replacing
            # a previously created copy of the same novel.
            with staged.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            if output.exists() and not replace:
                raise LocalImportError("Output appeared during conversion; refusing overwrite")
            staged.replace(output)
        finally:
            staged.unlink(missing_ok=True)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epub", type=Path, required=True)
    parser.add_argument("--source-url", required=True,
                        help="Royal Road /fiction/... or WTR-Lab /en/novel/... URL")
    parser.add_argument("--output-dir", type=Path, default=Path("Imported_Novels"))
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--replace", action="store_true",
                        help="Atomically replace an existing converted ZIP after verification")
    args = parser.parse_args(argv)
    try:
        output = import_epub_to_zip(
            args.epub, args.output_dir, args.source_url,
            confirm_rights=args.confirm_rights, replace=args.replace,
        )
        print(f"Created validated novel archive: {output}")
        return 0
    except (LocalImportError, OSError, ValueError, BadZipFile) as exc:
        print(f"EPUB import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
