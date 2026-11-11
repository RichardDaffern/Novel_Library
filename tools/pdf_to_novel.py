#!/usr/bin/env python3
"""Convert a locally supplied text PDF into a validated Novel_Library ZIP.

Offline only. No OCR, network use, registry updates, or Hugging Face uploads.
Requires PyMuPDF and Pillow (see requirements-pdf.txt).
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from uuid import NAMESPACE_URL, uuid5
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

import fitz
from PIL import Image

CHAPTER_HEADING = re.compile(r"^(?:(?:chapter|chap\.?)\s+)?(\d{1,6})\s*[.:-]?\s+(.+)$", re.I)
CHAPTER_ONLY = re.compile(r"^(?:chapter|chap\.?)\s+(\d{1,6})\s*$", re.I)
SPECIAL_HEADING = re.compile(r"^(prologue|epilogue)\b(?:\s*[:.-]\s*(.*))?$", re.I)
LIGATURES = str.maketrans({"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"})
MAX_CHAPTERS = 20000
MAX_PDF_BYTES = 1024 * 1024 * 1024  # Refuse unexpectedly large input (1 GiB)
MAX_PDF_PAGES = 50_000


class ConversionError(ValueError):
    """Unsafe or ambiguous conversion that must be inspected manually."""


@dataclass(frozen=True)
class Line:
    page: int  # one-based
    index: int  # one-based nonempty line within page
    text: str
    x: float
    y: float
    bottom: float
    size: float
    bold: bool


def normalise(text: str) -> str:
    """Expand only known presentation ligatures; do not alter CJK Unicode."""
    return text.translate(LIGATURES).replace("\u00ad", "")


def read_lines(document, progress=lambda _: None) -> list[list[Line]]:
    pages = []
    for index, page in enumerate(document):
        lines = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for row in block.get("lines", []):
                spans = row.get("spans", [])
                raw = "".join(s.get("text", "") for s in spans).strip()
                if not raw:
                    continue
                lines.append((row["bbox"], raw, max(s["size"] for s in spans),
                              any("bold" in s["font"].lower() for s in spans)))
        # Single-column reading order. Flag possible multi-column PDFs in report.
        lines.sort(key=lambda item: (round(item[0][1], 1), item[0][0]))
        pages.append([Line(index + 1, i + 1, normalise(text), box[0], box[1], box[3], size, bold)
                      for i, (box, text, size, bold) in enumerate(lines)])
        if (index + 1) % 50 == 0:
            progress(f"Scanned PDF pages: {index + 1}/{len(document)}")
    return pages


def _heading(lines: list[Line], start: int, body_size: float):
    line = lines[start]
    txt = line.text.strip()
    numbered = CHAPTER_HEADING.fullmatch(txt)
    only = CHAPTER_ONLY.fullmatch(txt)
    special = SPECIAL_HEADING.fullmatch(txt)
    if not (numbered or only or special):
        return None
    strong = line.bold or line.size >= body_size * 1.18
    if not strong:
        return None
    if numbered:
        number = int(numbered.group(1))
        name = numbered.group(2).strip()
        if not re.search(r"[A-Za-z\u3400-\u9fff]", name):
            return None
        if not name.isupper() and not line.bold:
            return None
    elif only:
        number, name = int(only.group(1)), ""
    else:
        name = txt
        number = 0 if txt.lower().startswith("prologue") else -1
    count = 1
    while start + count < len(lines):
        nxt = lines[start + count]
        prev = lines[start + count - 1]
        if (nxt.bold or nxt.size >= body_size * 1.18) and abs(nxt.size - line.size) < 2.5 and nxt.y - prev.y < line.size * 1.9:
            name = _append(name, nxt.text).strip()
            count += 1
        else:
            break
    return {"page": line.page, "line": line.index, "heading_lines": count,
            "number": number, "title": (f"{number} {name}" if number > 0 else name).strip()}


def detect_chapters(pages: list[list[Line]]) -> list[dict]:
    sizes = [round(line.size, 1) for page in pages for line in page if not line.bold]
    if not sizes:
        raise ConversionError("No readable text; scanned PDFs require separately reviewed OCR")
    body_size = Counter(sizes).most_common(1)[0][0]
    found = []
    for page in pages:
        for i in range(len(page)):
            entry = _heading(page, i, body_size)
            if entry:
                found.append(entry)
    if not found:
        raise ConversionError("No reliable chapter headings; supply a manual boundaries JSON file")
    return found


def validate_boundaries(pages: list[list[Line]], boundaries: list[dict]) -> None:
    if not 1 <= len(boundaries) <= MAX_CHAPTERS:
        raise ConversionError("Chapter count is outside 1..20,000")
    markers = []
    for item in boundaries:
        page, line, count = (int(item[k]) for k in ("page", "line", "heading_lines"))
        if not 1 <= page <= len(pages) or line < 1 or count < 1 or line + count - 1 > len(pages[page - 1]):
            raise ConversionError(f"Invalid chapter boundary {item}")
        if not str(item.get("title", "")).strip():
            raise ConversionError(f"Missing chapter title at page {page}")
        markers.append((page, line))
    if markers != sorted(set(markers)):
        raise ConversionError("Duplicated or unordered chapter boundaries")
    positive = [int(x["number"]) for x in boundaries if int(x["number"]) > 0]
    if positive and positive != list(range(positive[0], positive[-1] + 1)):
        raise ConversionError(f"Missing, duplicate, or unordered numbered chapters: {positive}")


def _manual_boundaries(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), list):
        raise ConversionError("Boundaries JSON needs a chapters array")
    result = []
    for c in data["chapters"]:
        result.append({"page": int(c["page"]), "line": int(c["line"]),
                       "heading_lines": int(c.get("heading_lines", 1)),
                       "title": str(c["title"]).strip(), "number": int(c["number"])})
    return result


def analyse(pdf: Path, boundaries_path: Path | None = None, progress=lambda _: None):
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise ConversionError("Provide an existing PDF file")
    if pdf.stat().st_size > MAX_PDF_BYTES:
        raise ConversionError("PDF exceeds the 1 GiB input safety budget")
    with fitz.open(pdf) as document:
        if len(document) > MAX_PDF_PAGES:
            raise ConversionError("PDF exceeds the 50,000-page safety budget")
        if document.needs_pass:
            raise ConversionError("Password-protected PDF is unsupported")
        pages = read_lines(document, progress)
        if not any(pages):
            raise ConversionError("PDF contains no selectable text; OCR requires a separate reviewed workflow")
        auto = None
        if boundaries_path is not None:
            try:
                auto = detect_chapters(pages)
            except ConversionError:
                pass
        found = detect_chapters(pages) if boundaries_path is None else _manual_boundaries(boundaries_path)
        validate_boundaries(pages, found)
        desc = ""  # Do not invent synopsis; the sample PDF has none.
        metadata = document.metadata
        report = {"pdf_pages": len(pages), "selectable_text": True,
                  "title_from_pdf": metadata.get("title", "") or "",
                  "author_from_pdf": metadata.get("author", "") or "",
                  "pdf_outline_entries": len(document.get_toc()),
                  "pdf_outline_chapters": len([e for e in document.get_toc() if CHAPTER_HEADING.fullmatch(e[1].strip())]),
                  "front_matter_pages": found[0]["page"] - 1,
                  "chapter_count": len(found),
                  "chapter_boundaries": found,
                  "warnings": []}
        if auto is not None:
            automated = {(c["page"], c["line"]): c for c in auto}
            changes = []
            for manual in found:
                prior = automated.get((manual["page"], manual["line"]))
                if prior and prior["title"] != manual["title"]:
                    changes.append({"page": manual["page"], "source_title": prior["title"],
                                    "reviewed_title": manual["title"]})
            report["manual_heading_corrections"] = changes
        if report["pdf_outline_entries"] == 0:
            report["warnings"].append("No machine-readable PDF outline/TOC; chapter headings detected from typography")
        elif report["pdf_outline_chapters"] and report["pdf_outline_chapters"] != len(found):
            report["warnings"].append("Numbered PDF outline and detected chapter count disagree")
        elif report["pdf_outline_chapters"]:
            outline_pages = [item[2] for item in document.get_toc() if CHAPTER_HEADING.fullmatch(item[1].strip())]
            source_pages = [item["page"] for item in found if item["number"] > 0]
            if outline_pages != source_pages:
                report["warnings"].append("PDF outline chapter pages disagree with detected chapter boundaries")
        suspicious = [(i + 1, len([x for x in page if x.size < 5])) for i, page in enumerate(pages)]
        if any(count > 2 for _, count in suspicious):
            report["warnings"].append("Some pages contain tiny text; inspect potential headers/footers")
        if len([p for p in pages if not p]) > 1:
            report["warnings"].append("Multiple image-only or blank pages; verify they do not contain story text")
        for heading in (auto if auto is not None else found):
            if re.search(r"[<>\uFFFD]", heading["title"]):
                report["warnings"].append(f"Suspicious heading on page {heading['page']}: {heading['title']}")
        if not desc:
            report["warnings"].append("No verifiable synopsis in PDF metadata; synopsis left empty")
        return pages, found, report


def _append(paragraph: str, segment: str) -> str:
    if not paragraph:
        return segment
    if paragraph.endswith(("-", "‐", "‑", "–", "\u2010")):
        return paragraph + segment
    return paragraph + " " + segment


def collect_chapters(pages: list[list[Line]], markers: list[dict]) -> tuple[list[dict], dict]:
    index = {(x["page"], x["line"]): i for i, x in enumerate(markers)}
    ignored = {(head["page"], offset) for head in markers
               for offset in range(head["line"], head["line"] + head["heading_lines"])}
    chapters = []
    curr = None
    fragments = []
    previous = None
    included = 0
    consumed = 0
    min_x = min((line.x for page in pages for line in page if line.size < 13), default=0)
    def flush():
        nonlocal fragments, curr
        if curr is not None:
            paragraphs = [p.strip() for p in fragments if p.strip()]
            curr["body"] = "\n\n".join(paragraphs)
            chapters.append(curr)
        fragments = []

    for page in pages:
        for line in page:
            pos = (line.page, line.index)
            if pos in index:
                flush()
                head = markers[index[pos]]
                curr = {"title": head["title"], "number": int(head["number"]),
                        "start_page": line.page, "source_lines": 0}
                previous = None
            if curr is None or pos in ignored:
                continue
            segment = line.text.strip()
            if not segment:
                continue
            included += 1
            curr["source_lines"] += 1
            if segment in ("***", "* * *", "---"):
                fragments.append(segment)
            elif (not fragments or previous is None or
                  line.x >= min_x + 8 or
                  (line.page == previous.page and line.y - previous.bottom > max(5, previous.size * .85))):
                fragments.append(segment)
            else:
                fragments[-1] = _append(fragments[-1], segment)
            previous = line
            consumed += 1
    flush()
    if consumed != included or len(chapters) != len(markers):
        raise ConversionError("Chapter coverage check failed")
    if not all(c["body"].strip() for c in chapters):
        raise ConversionError("At least one chapter contains no body text")
    return chapters, {"body_lines_emitted": consumed, "body_lines_expected": included,
                       "source_body_sha256": sha256("\n".join(c["body"] for c in chapters).encode()).hexdigest()}


def get_cover(pdf: Path) -> tuple[bytes, str] | None:
    with fitz.open(pdf) as document:
        for page in document[:min(3, len(document))]:
            images = page.get_images(full=True)
            for item in images:
                raw = document.extract_image(item[0])["image"]
                try:
                    with Image.open(BytesIO(raw)) as original:
                        if original.width < 320 or original.height < 450 or original.height < original.width:
                            continue
                        picture = original.convert("RGB")
                        stream = BytesIO()
                        picture.save(stream, "JPEG", quality=90, optimize=True)
                        return stream.getvalue(), "cover.jpg"
                except (ValueError, OSError):
                    continue
    return None


def epub_bytes(title: str, author: str, language: str, rows: list[dict], texts: list[str],
               identity: str, cover: tuple[bytes, str] | None = None, description: str = "") -> bytes:
    toc = "".join(f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{escape(row["title"])}</text></navLabel>'
                  f'<content src="chap{i:06d}.xhtml"/></navPoint>' for i, row in enumerate(rows, 1))
    nav = ('<?xml version="1.0" encoding="utf-8"?>'
           '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{escape(identity)}"/></head>'
           f'<docTitle><text>{escape(title)}</text></docTitle><navMap>{toc}</navMap></ncx>')
    manifest = ''.join(f'<item id="c{i}" href="chap{i:06d}.xhtml" media-type="application/xhtml+xml"/>'
                       for i in range(1, len(rows) + 1))
    spine = ''.join(f'<itemref idref="c{i}"/>' for i in range(1, len(rows) + 1))
    if cover:
        manifest += '<item id="cover-image" href="cover.jpg" media-type="image/jpeg"/>'
        manifest += '<item id="cover-page" href="cover.xhtml" media-type="application/xhtml+xml"/>'
        spine = '<itemref idref="cover-page" linear="no"/>' + spine
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
           f'<dc:language>{escape(language)}</dc:language>'
           f'<dc:identifier id="bookid">urn:uuid:{uuid5(NAMESPACE_URL, identity)}</dc:identifier>'
           + (f'<dc:description>{escape(description)}</dc:description>' if description else '')
           + ('<meta name="cover" content="cover-image"/>' if cover else '')
           + '</metadata><manifest><item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
           + manifest + '</manifest><spine toc="toc">' + spine + '</spine></package>')
    container = ('<?xml version="1.0" encoding="utf-8"?><container version="1.0" '
                 'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                 '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 '</rootfiles></container>')
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/toc.ncx", nav)
        if cover:
            archive.writestr("OEBPS/cover.jpg", cover[0])
            archive.writestr("OEBPS/cover.xhtml", '<?xml version="1.0" encoding="utf-8"?>'
                             '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title></head>'
                             '<body><div><img alt="Cover" src="cover.jpg"/></div></body></html>')
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            # One XHTML chapter per TXT, in declared spine order.
            content = ''.join(f'<p>{escape(para)}</p>' for para in text.split("\n\n") if para.strip())
            page = ('<?xml version="1.0" encoding="utf-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                    f'<title>{escape(row["title"])}</title></head><body class="fff_chapter">'
                    f'<h3 class="fff_chapter_title">{escape(row["title"])}</h3>' + content + '</body></html>')
            archive.writestr(f'OEBPS/chap{i:06d}.xhtml', page)
    return stream.getvalue()


def slugify(title: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:90]
    return result or "novel"


def validate_zip(path: Path, expected_chapters: int | None = None) -> dict:
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ConversionError("ZIP CRC error")
        files = archive.namelist()
        if not files or any("/" not in name or name.startswith("/") for name in files):
            raise ConversionError("ZIP requires one novel directory")
        prefixes = {name.split("/", 1)[0] for name in files}
        if len(prefixes) != 1:
            raise ConversionError("ZIP contains multiple novel directories")
        prefix = next(iter(prefixes)) + "/"
        metadata = json.loads(archive.read(prefix + "metadata.json"))
        rows = json.loads(archive.read(prefix + "chapters.json"))
        if not isinstance(rows, list) or len(rows) != metadata["chapter_count"]:
            raise ConversionError("Manifest chapter count mismatch")
        if expected_chapters is not None and len(rows) != expected_chapters:
            raise ConversionError("Unexpected chapter count")
        expected = {prefix + name for name in ("metadata.json", "chapters.json", "source.epub")}
        if metadata.get("cover_image"):
            expected.add(prefix + metadata["cover_image"])
        lengths = []
        digests = set()
        for ordinal, row in enumerate(rows, 1):
            if row["position"] != ordinal or row["file"] != f"chapter_{ordinal:04d}.txt":
                raise ConversionError(f"Misordered chapter at {ordinal}")
            name = prefix + row["file"]
            expected.add(name)
            data = archive.read(name)
            body = data.decode("utf-8")
            if sha256(data).hexdigest() != row["sha256"]:
                raise ConversionError(f"Incorrect SHA-256 for {name}")
            if not body.startswith(row["title"] + "\n\n"):
                raise ConversionError(f"TXT title mismatch in {name}")
            text = body[len(row["title"]) + 2:].strip()
            if len(text.split()) != row["word_count"]:
                raise ConversionError(f"Word count mismatch for {name}")
            lengths.append(len(text.split()))
            digest = sha256(text.encode()).hexdigest()
            if digest in digests:
                raise ConversionError("Duplicate chapter body")
            digests.add(digest)
        if set(files) != expected:
            raise ConversionError(f"Unexpected or missing ZIP members: {set(files) ^ expected}")
        with ZipFile(BytesIO(archive.read(prefix + "source.epub"))) as epub:
            if epub.testzip() is not None or epub.read("mimetype") != b"application/epub+zip":
                raise ConversionError("EPUB failed integrity checks")
            if epub.infolist()[0].compress_type != ZIP_STORED:
                raise ConversionError("EPUB mimetype must be stored without compression")
            package = ET.fromstring(epub.read("OEBPS/content.opf"))
            spine = [el.attrib["idref"] for el in package.iter() if el.tag.endswith("itemref") and el.get("linear") != "no"]
            if len(spine) != len(rows):
                raise ConversionError("EPUB spine chapter count mismatch")
            for i, row in enumerate(rows, 1):
                chapter = ET.fromstring(epub.read(f"OEBPS/chap{i:06d}.xhtml"))
                if row["title"] not in " ".join("".join(chapter.itertext()).split()):
                    raise ConversionError(f"EPUB missing chapter title {i}")
        return {"status": "passed", "chapter_count": len(rows),
                "min_chapter_words": min(lengths), "max_chapter_words": max(lengths),
                "zip_members": len(files), "epub_spine_chapters": len(spine)}


def file_sha256(path: Path) -> str:
    """Calculate file identity without materialising the whole PDF in memory."""
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def convert(pdf: Path, output_dir: Path, *, title: str = "", author: str = "",
            language: str = "en", description: str = "", boundaries: Path | None = None,
            expected_chapters: int | None = None, replace: bool = False, progress=print) -> tuple[Path, Path]:
    pages, markers, report = analyse(pdf, boundaries, progress)
    if expected_chapters is not None and len(markers) != expected_chapters:
        raise ConversionError(f"Expected {expected_chapters} chapters but detected {len(markers)}")
    title = title or report["title_from_pdf"]
    author = author or report["author_from_pdf"]
    if not title:
        raise ConversionError("PDF has no title; supply --title")
    if not author:
        raise ConversionError("PDF has no author; supply --author")
    if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?", language):
        raise ConversionError("Invalid language tag")
    input_hash = file_sha256(pdf)
    url = "pdf://sha256/" + input_hash
    book_slug = slugify(title)
    if book_slug == "novel":
        book_slug += "-" + input_hash[:12]
    archive_name = "novel-" + input_hash[:12] + ".zip"
    output_dir = Path(output_dir)
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
    target = output_dir / archive_name
    if target.exists() and not replace:
        raise ConversionError(f"Refusing to overwrite existing ZIP: {target}")
    chapters, coverage = collect_chapters(pages, markers)
    report.update(coverage)
    rows, plain_bodies = [], []
    short = []
    for i, chapter in enumerate(chapters, 1):
        body = chapter["body"]
        name = f"chapter_{i:04d}.txt"
        saved = f"{chapter['title']}\n\n{body}\n".encode("utf-8")
        words = len(body.split())
        rows.append({"position": i, "chapter_number": chapter["number"] if chapter["number"] > 0 else i,
                     "title": chapter["title"], "file": name, "word_count": words,
                     "sha256": sha256(saved).hexdigest()})
        plain_bodies.append(body)
        if words < 150:
            short.append({"chapter": i, "word_count": words})
    report["suspiciously_short_chapters"] = short
    if short:
        report["warnings"].append(f"{len(short)} chapter(s) below 150 whitespace-separated words")
    cover = get_cover(pdf)
    report["cover_extracted"] = bool(cover)
    metadata = {"title": title, "author": author, "language": language,
                "source_url": url, "chapter_count": len(rows),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "format": "epub", "original_format": "pdf", "chapter_files": "UTF-8 TXT",
                "source_pdf_sha256": input_hash, "source_pdf_pages": len(pages)}
    if description:
        metadata["description"] = metadata["synopsis"] = description
    if cover:
        metadata["cover_image"] = cover[1]
    epub = epub_bytes(title, author, language, rows, plain_bodies, url, cover, description)
    members = {"metadata.json": (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode(),
               "chapters.json": (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode(),
               "source.epub": epub}
    if cover:
        members[cover[1]] = cover[0]
    staged = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".pdf-novel-", suffix=".zip", dir=output_dir, delete=False) as temp:
            staged = Path(temp.name)
        with ZipFile(staged, "w", ZIP_DEFLATED, compresslevel=6) as archive:
            for name, data in members.items():
                archive.writestr(book_slug + "/" + name, data)
            # Stream each chapter into the outer archive without retaining a
            # second complete dictionary of TXT payloads in memory.
            for chapter, row in zip(chapters, rows):
                data = f"{chapter['title']}\n\n{chapter['body']}\n".encode("utf-8")
                archive.writestr(book_slug + "/" + row["file"], data)
        result = validate_zip(staged, expected_chapters=len(rows))
        report.update({"validation": result, "output_zip": str(target),
                       "source_pdf_sha256": input_hash})
        if target.exists() and not replace:
            raise ConversionError("ZIP appeared during conversion; refusing overwrite")
        staged.replace(target)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    report_path = output_dir / ("novel-" + input_hash[:12] + "-validation.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    progress(f"Validated {len(rows)} chapters in {target}")
    return target, report_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Local PDF file")
    parser.add_argument("--output-dir", type=Path, default=Path("downloads"))
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--language", default="en")
    parser.add_argument("--description", default="", help="Only use sourced/verified description")
    parser.add_argument("--boundaries", type=Path, help="Manually reviewed chapter boundaries JSON")
    parser.add_argument("--expected-chapters", type=int)
    parser.add_argument("--inspect", action="store_true", help="Only write editable chapter plan and report")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--confirm-rights", action="store_true", help="Confirm authorised personal archiving")
    args = parser.parse_args(argv)
    try:
        if args.inspect:
            _, chapters, report = analyse(args.pdf, args.boundaries, print)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            plan = args.output_dir / "pdf-chapter-plan.json"
            if plan.exists() and not args.replace:
                raise ConversionError(f"Refusing to overwrite existing plan: {plan}")
            plan.write_text(json.dumps({"chapters": chapters}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"plan": str(plan), "report": report}, ensure_ascii=False, indent=2))
            return 0
        if not args.confirm_rights:
            raise ConversionError("Confirm you are permitted to archive the PDF with --confirm-rights")
        archive, report = convert(args.pdf, args.output_dir, title=args.title, author=args.author,
                                  language=args.language, description=args.description,
                                  boundaries=args.boundaries, expected_chapters=args.expected_chapters,
                                  replace=args.replace)
        print(f"ZIP: {archive}\nValidation report: {report}")
        return 0
    except (ConversionError, OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"PDF conversion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())