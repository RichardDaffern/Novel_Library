#!/usr/bin/env python3
"""Offline EPUB/TXT exporter for up to TWO user-supplied, authorised chapters.

No networking, WebNovel scraping, authentication, paywall access, or DRM handling.
This tool is intentionally independent of NovelFull.
"""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import re
import sys
from uuid import uuid5, NAMESPACE_URL
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

MAX_CHAPTERS = 2
MAX_INPUT_BYTES = 2_000_000


class ExportError(ValueError):
    """Invalid or unauthorised input."""


def _clean(value, name, limit=240):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ExportError(f"{name} must be non-empty text of at most {limit} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ExportError(f"{name} contains invalid control characters")
    return value.strip()


def validate(data):
    if not isinstance(data, dict):
        raise ExportError("Input must be a JSON object")
    title = _clean(data.get("title"), "title")
    author = _clean(data.get("author"), "author")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not 1 <= len(chapters) <= MAX_CHAPTERS:
        raise ExportError("Exactly one or two chapters are permitted")
    if data.get("source") not in {"user-supplied-authorised", "webnovel-public-with-user-confirmed-rights"}:
        raise ExportError("source must identify authorised local or public text")
    result = []
    for index, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict):
            raise ExportError("Each chapter must be an object")
        position = ch.get("position")
        if type(position) is not int or position != index:
            raise ExportError("Chapter positions must be consecutive, starting at 1")
        chapter_title = _clean(ch.get("title"), f"chapter {index} title")
        body = _clean(ch.get("text"), f"chapter {index} text", 500_000)
        if len(body) < 10:
            raise ExportError(f"Chapter {index} text is unexpectedly short")
        result.append({"position": index, "title": chapter_title, "text": body})
    return title, author, result


def export(data, output_dir):
    title, author, chapters = validate(data)
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ExportError("Output directory must be empty to avoid overwriting existing files")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for ch in chapters:
        filename = f"chapter-{ch['position']:02d}.txt"
        (output_dir / filename).write_text(
            f"{ch['title']}\n\n{ch['text']}\n", encoding="utf-8"
        )
        manifest.append({"position": ch["position"], "title": ch["title"], "file": filename})
    combined = title + "\n" + author + "\n\n" + "\n\n".join(
        f"{c['title']}\n\n{c['text']}" for c in chapters
    ) + "\n"
    (output_dir / "book.txt").write_text(combined, encoding="utf-8")
    metadata = {"title": title, "author": author, "source": data["source"],
                "chapter_count": len(chapters), "chapters": manifest}
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    uid = str(uuid5(NAMESPACE_URL, title + "\n" + author))
    ncx_nav = "".join(
        f'<navPoint id="nav{i}" playOrder="{i}"><navLabel><text>{escape(c["title"])}</text></navLabel>'
        f'<content src="chapter-{i:02d}.xhtml"/></navPoint>'
        for i, c in enumerate(chapters, 1)
    )
    manifest_items = "".join(
        f'<item id="ch{i}" href="chapter-{i:02d}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(1, len(chapters) + 1)
    )
    spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(1, len(chapters) + 1))
    opf = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="bookid">urn:uuid:{uid}</dc:identifier>'
           f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
           f'<dc:language>en</dc:language></metadata>'
           f'<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
           f'{manifest_items}</manifest><spine toc="ncx">{spine}</spine></package>')
    ncx = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="urn:uuid:{uid}"/></head>'
           f'<docTitle><text>{escape(title)}</text></docTitle><navMap>{ncx_nav}</navMap></ncx>')
    with ZipFile(output_dir / "book.epub", "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            '</rootfiles></container>', compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", opf, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/toc.ncx", ncx, compress_type=ZIP_DEFLATED)
        for ch in chapters:
            paragraphs = "".join(f"<p>{escape(p)}</p>" for p in re.split(r"\n\s*\n", ch["text"]))
            page = ('<?xml version="1.0" encoding="utf-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                    f'<title>{escape(ch["title"])}</title></head><body>'
                    f'<h1>{escape(ch["title"])}</h1>{paragraphs}</body></html>')
            archive.writestr(f"OEBPS/chapter-{ch['position']:02d}.xhtml",
                             page, compress_type=ZIP_DEFLATED)
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Local JSON with authorised text")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input.stat().st_size > MAX_INPUT_BYTES:
            raise ExportError("Input JSON file exceeds safety size limit")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        manifest = export(data, args.output_dir)
        print(json.dumps(manifest, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WebNovel offline export failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
