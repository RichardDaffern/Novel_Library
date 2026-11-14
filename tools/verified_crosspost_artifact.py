#!/usr/bin/env python3
"""Prepare one already validated novel ZIP for standard GitHub Actions delivery.

The FicHub cross-post downloader produces a full reader ZIP. Upload the
contained book directory, not the ZIP itself, so GitHub's artefact ZIP has the
same layout as NovelFull's existing artefacts and Windows retrieval tool.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from zipfile import BadZipFile, ZipFile

from tools.download_registry import canonical_url
from tools.verified_crosspost_download import (
    CrosspostDownloadError, _verified_record,
)

CHAPTER_NAME = re.compile(r"chapter_[0-9]+\.txt")
BOOK_DIR = re.compile(r"[a-z0-9][a-z0-9._-]{0,199}")


def prepare_artifact(archive_path: Path, output_dir: Path, source_url: str) -> Path:
    """Create a single validated book directory, without partial publication."""
    canonical, _, entry = _verified_record(source_url)
    archive_path, output_dir = Path(archive_path), Path(output_dir)
    if output_dir.exists():
        raise CrosspostDownloadError("Artefact output already exists; refusing overwrite")
    with ZipFile(archive_path) as archive:
        names = archive.namelist()
        if not names or len(set(names)) != len(names) or archive.testzip() is not None:
            raise CrosspostDownloadError("Corrupt ZIP or duplicate archive entries")
        parts = [name.split("/") for name in names]
        if (any(len(p) != 2 for p in parts)
                or any(not BOOK_DIR.fullmatch(p[0]) for p in parts)
                or len({p[0] for p in parts}) != 1):
            raise CrosspostDownloadError("ZIP must contain exactly one safe novel folder")
        slug = parts[0][0]
        files = {p[1] for p in parts}
        required = {"metadata.json", "chapters.json", "source.epub"}
        if not required.issubset(files):
            raise CrosspostDownloadError("ZIP lacks required EPUB or manifests")
        meta = json.loads(archive.read(f"{slug}/metadata.json"))
        rows = json.loads(archive.read(f"{slug}/chapters.json"))
        if not isinstance(meta, dict) or not isinstance(rows, list):
            raise CrosspostDownloadError("Invalid ZIP metadata or chapter manifest")
        if canonical_url(meta.get("source_url", "")) != canonical_url(canonical):
            raise CrosspostDownloadError("ZIP source URL differs from the selected novel")
        if (not entry["minimum_chapters"] <= len(rows) <= 20000
                or meta.get("chapter_count") != len(rows)):
            raise CrosspostDownloadError("Missing or implausible chapter count")
        chapter_names = set()
        for expected_position, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise CrosspostDownloadError("Invalid chapter record")
            name = row.get("file")
            if (row.get("position") != expected_position or
                    not isinstance(name, str) or
                    not CHAPTER_NAME.fullmatch(name) or
                    name in chapter_names):
                raise CrosspostDownloadError("Invalid chapter filename or position")
            chapter_names.add(name)
            if sha256(archive.read(f"{slug}/{name}")).hexdigest() != row.get("sha256"):
                raise CrosspostDownloadError("Chapter SHA-256 differs from manifest")
        if rows[0].get("title") != entry["first_chapter_title"]:
            raise CrosspostDownloadError("Unexpected first story chapter")
        for checkpoint in entry.get("chapter_checkpoints", []):
            index = checkpoint["position"] - 1
            if index >= len(rows) or rows[index].get("title") != checkpoint["title"]:
                raise CrosspostDownloadError("Chapter identity checkpoint mismatch")
        expected = required | chapter_names
        cover = meta.get("cover_image")
        if cover:
            if cover not in ("cover.png", "cover.jpg"):
                raise CrosspostDownloadError("Unexpected cover filename")
            expected.add(cover)
        if files != expected or len(names) != len(expected):
            raise CrosspostDownloadError("ZIP contains unexpected or missing files")
        if archive.getinfo(f"{slug}/source.epub").file_size < 100:
            raise CrosspostDownloadError("Source EPUB is empty")
        if sum(archive.getinfo(n).file_size for n in names) > 800 * 1024 * 1024:
            raise CrosspostDownloadError("Archive exceeds safe expanded size")

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="novel-artifact-", dir=output_dir.parent) as tmp:
            staging = Path(tmp) / "staged"
            book = staging / slug
            book.mkdir(parents=True)
            for name in sorted(expected):
                with archive.open(f"{slug}/{name}") as source, (book / name).open("wb") as target:
                    shutil.copyfileobj(source, target)
            for row in rows:
                if sha256((book / row["file"]).read_bytes()).hexdigest() != row["sha256"]:
                    raise CrosspostDownloadError("Staged chapter SHA-256 mismatch")
            staging.replace(output_dir)
    return output_dir / slug


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("downloads"))
    args = parser.parse_args(argv)
    try:
        archives = list(args.archive_dir.glob("novel-*.zip"))
        if len(archives) != 1:
            raise CrosspostDownloadError("Expected exactly one complete novel ZIP")
        book = prepare_artifact(archives[0], args.output_dir, args.source_url)
        print(f"Prepared one verified Actions novel folder: {book}")
        return 0
    except (CrosspostDownloadError, BadZipFile, ValueError, KeyError, OSError, TypeError) as exc:
        print(f"Actions artefact preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
