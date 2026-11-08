#!/usr/bin/env python3
"""Import at most two locally saved, authorised WebNovel chapters into EPUB/TXT.

This module never contacts WebNovel or any other website. It reads HTML/TXT
files already saved by the user through normal, permitted means. It does not
touch the NovelFull implementation or access browser sessions/cookies.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from tools.webnovel_export import ExportError, export
from tools.webnovel_public_two_chapter import PublicChapterError, parse_public_chapter

MAX_LOCAL_BYTES = 4 * 1024 * 1024
SUPPORTED_SUFFIXES = {".htm", ".html", ".txt"}


class SavedPageError(ValueError):
    """The supplied file or saved chapter is unsuitable for export."""


def read_saved_chapter(path: Path, title: str) -> str:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise SavedPageError(f"Unsupported chapter file type: {path.suffix or '(none)'}")
    if not path.is_file():
        raise SavedPageError(f"Chapter file does not exist: {path.name}")
    if path.stat().st_size > MAX_LOCAL_BYTES:
        raise SavedPageError("Chapter file exceeds the 4 MiB safety limit")
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() in {".htm", ".html"}:
        try:
            return parse_public_chapter(content, "", title)
        except PublicChapterError as exc:
            raise SavedPageError(f"{path.name}: {exc}") from exc
    if len(content.strip()) < 100:
        raise SavedPageError(f"{path.name}: chapter text is unexpectedly short")
    return content.strip()


def import_saved_pages(
    book_title: str,
    author: str,
    chapter_files,
    chapter_titles,
    output_dir,
    *,
    confirm_rights=False,
):
    """Convert one or two user-saved chapter files without any network calls."""
    if not confirm_rights:
        raise SavedPageError("Explicit --confirm-rights is required")
    if not 1 <= len(chapter_files) <= 2 or len(chapter_files) != len(chapter_titles):
        raise SavedPageError("Supply exactly one or two chapter files with matching titles")
    sources = [Path(p) for p in chapter_files]
    if len({p.resolve() for p in sources}) != len(sources):
        raise SavedPageError("Chapter files must be distinct and ordered")
    chapters = []
    for position, (path, title) in enumerate(zip(sources, chapter_titles), start=1):
        body = read_saved_chapter(path, title)
        chapters.append({"position": position, "title": title, "text": body})
    return export(
        {
            "source": "user-supplied-authorised",
            "title": book_title,
            "author": author,
            "chapters": chapters,
        },
        output_dir,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-title", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--chapter-1", type=Path, required=True)
    parser.add_argument("--chapter-1-title", default="Chapter 1")
    parser.add_argument("--chapter-2", type=Path)
    parser.add_argument("--chapter-2-title", default="Chapter 2")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confirm-rights", action="store_true")
    args = parser.parse_args(argv)
    paths = [args.chapter_1]
    titles = [args.chapter_1_title]
    if args.chapter_2 is not None:
        paths.append(args.chapter_2)
        titles.append(args.chapter_2_title)
    try:
        result = import_saved_pages(
            args.book_title, args.author, paths, titles,
            args.output_dir, confirm_rights=args.confirm_rights,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (SavedPageError, ExportError, OSError) as exc:
        print(f"WebNovel saved-page import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
