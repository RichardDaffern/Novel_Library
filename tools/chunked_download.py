#!/usr/bin/env python3
"""Bounded, resumable chapter batches and EPUB assembly for authorised archives.

The GitHub workflow runs independent chapter ranges in separate jobs. A rerun
can reuse validated complete range artifacts while they remain available.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit
import zipfile

from tools.download_registry import canonical_url, normalise_range
from novel_downloader import epub_chapters, slugify

DEFAULT_CHUNK_SIZE = 200
MAX_CHUNKS = 128
SYNTHETIC_URL = "http://test1.com?sid=123"


def identity(url: str) -> str:
    return sha256(url.encode("utf-8")).hexdigest()[:20]


def chapter_plan(url: str, total: int, chapter_range: str = "",
                 chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    if not isinstance(total, int) or total < 1:
        raise ValueError("Chapter discovery returned no positive chapter count")
    if not 1 <= chunk_size <= 1000:
        raise ValueError("Chunk size must be between 1 and 1000")
    selected = normalise_range(chapter_range)
    first, last = (1, total) if selected == "all" else tuple(map(int, selected.split("-")))
    if last > total:
        raise ValueError(f"Requested chapter {last}, but story index contains only {total}")
    key = identity(url)
    pieces = [
        {"start": start, "end": min(last, start + chunk_size - 1), "name": f"chapter-batch-{key}-{start:05d}-{min(last, start + chunk_size - 1):05d}"}
        for start in range(first, last + 1, chunk_size)
    ]
    if len(pieces) > MAX_CHUNKS:
        raise ValueError(f"{len(pieces)} ranges exceeds {MAX_CHUNKS} GitHub jobs; select a smaller chapter range")
    return {
        "version": 1, "url": url, "key": key, "range": selected,
        "total_chapters": total, "first": first, "last": last, "pieces": pieces,
    }


def _github_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as file:
            file.write(f"{name}={value}\n")


def chapter_count_from_metadata(data: dict) -> int:
    """Accept FanFicFare counts such as 4035, "4035", or "4,035".

    Validate the entire numeric value instead of silently truncating a malformed
    chapter count, as doing so would produce incomplete output.
    """
    count = data.get("numChapters")
    if count is None:
        chapters = data.get("zchapters")
        if not isinstance(chapters, list):
            raise ValueError("FanFicFare metadata has no chapter count or chapter list")
        count = len(chapters)
    elif isinstance(count, str):
        raw = count.strip()
        if not re.fullmatch(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)", raw):
            raise ValueError(f"Invalid FanFicFare chapter count: {count!r}")
        count = int(raw.replace(",", ""))
    elif type(count) is not int:
        raise ValueError(f"Invalid FanFicFare chapter count type: {type(count).__name__}")
    if count < 1:
        raise ValueError(f"FanFicFare returned no chapters: {count}")
    return count


def discover_count(url: str, timeout_minutes: int = 15) -> int:
    completed = subprocess.run(
        [sys.executable, "novel_downloader.py", url, "--confirm-rights", "--list-only",
         "--timeout-minutes", str(timeout_minutes)],
        capture_output=True, text=True, check=True, timeout=timeout_minutes * 60 + 30,
    )
    data = json.loads(completed.stdout.strip())
    return chapter_count_from_metadata(data)


def _manifest_file(folder: Path) -> Path:
    return folder / "part.json"


def _source_key(url: str) -> str:
    return url if url == SYNTHETIC_URL else canonical_url(url)


def validate_piece(folder: Path, url: str, key: str, first: int, last: int) -> dict:
    manifest = json.loads(_manifest_file(folder).read_text(encoding="utf-8"))
    if (manifest.get("version") != 1 or manifest.get("url") != _source_key(url)
            or manifest.get("key") != key or manifest.get("start") != first
            or manifest.get("end") != last):
        raise ValueError(f"Incorrect chapter batch identity: {folder}")
    book_dir = folder / "book"
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    if _source_key(metadata.get("source_url", "")) != _source_key(url):
        raise ValueError("Chapter batch belongs to a different source URL")
    rows = json.loads((book_dir / "chapters.json").read_text(encoding="utf-8"))
    expected = list(range(first, last + 1))
    if [x.get("position") for x in rows] != expected:
        raise ValueError(f"Incomplete chapter batch {first}-{last}")
    if len(rows) != metadata.get("chapter_count"):
        raise ValueError("Chapter batch manifest and metadata counts differ")
    if not (book_dir / "source.epub").is_file():
        raise ValueError("Missing source EPUB in chapter batch")
    for row in rows:
        name = row.get("file", "")
        if not name or Path(name).name != name:
            raise ValueError("Unsafe chapter filename in chapter batch")
        chapter_file = book_dir / name
        if not chapter_file.is_file() or chapter_file.stat().st_size < 30:
            raise ValueError(f"Missing or empty chapter file: {name}")
        if row.get("sha256") != sha256(chapter_file.read_text(encoding="utf-8").encode("utf-8")).hexdigest():
            raise ValueError(f"Invalid chapter checksum: {name}")
    return {"metadata": metadata, "chapters": rows, "folder": book_dir}


def _prior_artifacts(name: str, repository: str) -> list[dict]:
    if not repository or not os.environ.get("GH_TOKEN"):
        return []
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repository}/actions/artifacts?name={name}&per_page=100"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(result.stdout)
        current_run = str(os.environ.get("GITHUB_RUN_ID", ""))
        return [
            item for item in data.get("artifacts", [])
            if item.get("name") == name and not item.get("expired")
            and str((item.get("workflow_run") or {}).get("id", "")) != current_run
        ]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def reuse_complete_piece(folder: Path, url: str, key: str, first: int, last: int) -> bool:
    name = f"chapter-batch-{key}-{first:05d}-{last:05d}"
    for artifact in _prior_artifacts(name, os.environ.get("GITHUB_REPOSITORY", ""))[:5]:
        run = (artifact.get("workflow_run") or {}).get("id")
        if not run:
            continue
        with tempfile.TemporaryDirectory(prefix="novel-batch-reuse-") as tmp:
            candidate = Path(tmp)
            try:
                subprocess.run(
                    ["gh", "run", "download", str(run), "-n", name, "-D", str(candidate)],
                    check=True, capture_output=True, text=True, timeout=120,
                )
                validate_piece(candidate, url, key, first, last)
                shutil.copytree(candidate, folder, dirs_exist_ok=True)
                print(f"REUSED completed chapters {first}-{last} from run {run}", flush=True)
                return True
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                print(f"Ignoring invalid/unavailable cached range {first}-{last}: {exc}", flush=True)
    return False


def fetch_piece(url: str, key: str, first: int, last: int, folder: Path,
                scratch: Path, timeout_minutes: int = 65,
                force: bool = False, self_test: bool = False) -> None:
    if key != identity(url) or first < 1 or last < first:
        raise ValueError("Invalid chapter batch identity or boundaries")
    if not force and reuse_complete_piece(folder, url, key, first, last):
        return
    cmd = [
        sys.executable, "-u", "novel_downloader.py",
        "--self-test" if self_test else url, "--confirm-rights",
        "--chapter-range", f"{first}-{last}", "--output-dir", str(scratch),
        "--timeout-minutes", str(timeout_minutes),
    ]
    print(f"Downloading bounded chapter batch {first}-{last}", flush=True)
    subprocess.run(cmd, check=True, timeout=timeout_minutes * 60 + 30)
    metadata_files = list(scratch.rglob("metadata.json"))
    if len(metadata_files) != 1:
        raise ValueError(f"Expected one chapter batch output, found {len(metadata_files)}")
    source_dir = metadata_files[0].parent
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, folder / "book", dirs_exist_ok=True)
    (_manifest_file(folder)).write_text(json.dumps({
        "version": 1, "url": _source_key(url), "key": key,
        "start": first, "end": last,
    }, indent=2) + "\n", encoding="utf-8")
    validate_piece(folder, url, key, first, last)
    print(f"VERIFIED completed chapter batch {first}-{last}", flush=True)


def _epub(book: Path, rows: list[dict], title: str, author: str, language: str, url: str) -> None:
    def chapter_xhtml(chapter: dict) -> str:
        content = (book / chapter["file"]).read_text(encoding="utf-8")
        lines = content.split("\n", 2)
        body = lines[2] if len(lines) == 3 else content
        paragraphs = [
            f"<p>{escape(paragraph)}</p>"
            for paragraph in body.split("\n\n") if paragraph.strip()
        ]
        return ('<?xml version="1.0" encoding="utf-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                f'<title>{escape(chapter["title"])}</title></head>'
                '<body class="fff_chapter">'
                f'<h3 class="fff_chapter_title">{escape(chapter["title"])}</h3>'
                + "".join(paragraphs) + '</body></html>')

    manifest = [
        f'<item id="chap{i}" href="chap{i:06d}.xhtml" media-type="application/xhtml+xml" />'
        for i in range(1, len(rows) + 1)
    ]
    spine = [f'<itemref idref="chap{i}" />' for i in range(1, len(rows) + 1)]
    package = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
        f'<dc:language>{escape(language or "en")}</dc:language>'
        f'<dc:identifier id="bookid">urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, url)}</dc:identifier>'
        '</metadata><manifest><item id="toc" href="toc.ncx" '
        'media-type="application/x-dtbncx+xml" />'
        + "".join(manifest) +
        '</manifest><spine toc="toc">' + "".join(spine) + '</spine></package>'
    )
    navpoints = "".join(
        f'<navPoint id="nav{i}" playOrder="{i}">'
        f'<navLabel><text>{escape(row["title"])}</text></navLabel>'
        f'<content src="chap{i:06d}.xhtml"/></navPoint>'
        for i, row in enumerate(rows, 1)
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="{escape(url)}"/></head>'
        f'<docTitle><text>{escape(title)}</text></docTitle>'
        '<navMap>' + navpoints + '</navMap></ncx>'
    )
    container = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    with zipfile.ZipFile(book / "source.epub", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", package)
        z.writestr("OEBPS/toc.ncx", ncx)
        for i, row in enumerate(rows, 1):
            z.writestr(f"OEBPS/chap{i:06d}.xhtml", chapter_xhtml(row))


def assembled_title(title: str, first_chunk: dict) -> str:
    """Remove the chapter-range suffix introduced by FanFicFare's range export.

    The title of a chapter-range EPUB may be, for example,
    "Novel Name (Ch 1-200)". The assembled book must carry the novel's name,
    not the label of the first 200-chapter intermediate file.
    """
    if not title:
        return title
    first = first_chunk["start"]
    last = first_chunk["end"]
    suffix = re.compile(rf"\s*\(Ch\s*{first}\s*-\s*{last}\)$", flags=re.IGNORECASE)
    return (suffix.sub("", title.strip()) or title).strip()


def assemble(plan: dict, chunks_dir: Path, output_dir: Path) -> Path:
    key, url = plan["key"], plan["url"]
    if key != identity(url):
        raise ValueError("Invalid assembled-novel identity")
    all_rows: list[dict] = []
    titles: list[dict] = []
    for piece in plan["pieces"]:
        artifact_name = f"chapter-batch-{key}-{piece['start']:05d}-{piece['end']:05d}"
        chunk = chunks_dir / artifact_name
        validated = validate_piece(chunk, url, key, piece["start"], piece["end"])
        titles.append(validated["metadata"])
        for row in validated["chapters"]:
            all_rows.append({**row, "_source": str(validated["folder"] / row["file"])})
    positions = [row["position"] for row in all_rows]
    if positions != list(range(plan["first"], plan["last"] + 1)):
        raise ValueError("Missing, duplicated or unordered chapters during assembly")
    book = output_dir / slugify("fanficfare-smoke-test" if url == SYNTHETIC_URL else (Path(urlsplit(url).path).stem or "novel"))
    book.mkdir(parents=True, exist_ok=True)
    merged: list[dict] = []
    for row in all_rows:
        dest = f"chapter_{row['position']:05d}.txt"
        shutil.copyfile(row["_source"], book / dest)
        if sha256((book / dest).read_text(encoding="utf-8").encode("utf-8")).hexdigest() != row["sha256"]:
            raise ValueError(f"Failed to verify combined chapter {row['position']}")
        merged.append({k: v for k, v in row.items() if k != "_source"} | {"file": dest})
    first_metadata = titles[0]
    title = assembled_title(first_metadata.get("title") or book.name, plan["pieces"][0])
    author = first_metadata.get("author") or ""
    language = first_metadata.get("language") or "en"
    _epub(book, merged, title, author, language, url)
    epub_metadata, from_epub = epub_chapters(book / "source.epub")
    if len(from_epub) != len(merged):
        raise ValueError("Combined EPUB does not contain every selected chapter")
    metadata = {
        "title": title, "author": author, "language": language,
        "source_url": url, "chapter_count": len(merged),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "format": "epub", "chapter_files": "UTF-8 TXT",
        "assembled_from_batches": len(plan["pieces"]),
    }
    (book / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (book / "chapters.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ASSEMBLED {len(merged)} verified TXT chapters and EPUB in {book}", flush=True)
    return book


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "fetch", "assemble"])
    parser.add_argument("--url", default="")
    parser.add_argument("--chapter-range", default="")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--total", type=int, default=0, help="Offline chapter count for tests")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--key", default="")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=0)
    parser.add_argument("--timeout-minutes", type=int, default=65)
    parser.add_argument("--plan-file", type=Path, default=Path("chapter_plan.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("chapter_batch"))
    parser.add_argument("--scratch-dir", type=Path, default=Path("scratch"))
    parser.add_argument("--chunks-dir", type=Path, default=Path("completed_batches"))
    args = parser.parse_args(argv)
    url = SYNTHETIC_URL if args.self_test else canonical_url(args.url)
    if args.action == "plan":
        total = 9 if args.self_test else (args.total or discover_count(url))
        plan = chapter_plan(url, total, args.chapter_range, args.chunk_size)
        args.plan_file.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        matrix = json.dumps({"include": plan["pieces"]}, separators=(",", ":"))
        for field in ("key", "first", "last"):
            _github_output(field, str(plan[field]))
        _github_output("matrix", matrix)
        print(f"INDEXED {total} chapters: {len(plan['pieces'])} batches for {plan['first']}-{plan['last']}", flush=True)
        return 0
    if args.action == "fetch":
        fetch_piece(url, args.key, args.start, args.end, args.output_dir,
                    args.scratch_dir, args.timeout_minutes, args.force, args.self_test)
        return 0
    if args.action == "assemble":
        plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
        if plan["url"] != url:
            raise ValueError("Cannot assemble batches from a different novel")
        assemble(plan, args.chunks_dir, args.output_dir)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
