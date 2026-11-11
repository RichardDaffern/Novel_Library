"""Preserve FanFicFare source genres, synopsis and status when assembling batch EPUBs.

No network access or chapter text extraction. Parse only the EPUB's package XML.
"""
from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

STATUS = {"completed": "Completed", "complete": "Completed",
          "in-progress": "Ongoing", "in progress": "Ongoing", "ongoing": "Ongoing"}
NOISE = re.compile(r"^(?:last\s+update(?:\b|\s*[:/])|updated\b|language\s*:|status\s*:)", re.I)


def clean_genres(values) -> list[str]:
    """Stable, case-insensitive dedupe, excluding timestamp and status subjects."""
    result: list[str] = []
    seen: set[str] = set()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return result
    for raw in values:
        if not isinstance(raw, str):
            continue
        genre = " ".join(raw.split()).strip()
        key = genre.casefold()
        if (not genre or len(genre) > 100 or key in seen or key in STATUS
                or NOISE.match(genre)):
            continue
        result.append(genre)
        seen.add(key)
    return result


def source_metadata_from_package(package: ET.Element) -> dict:
    fields: dict[str, list[str]] = {}
    for element in package.iter():
        # Only Dublin Core fields, not OPF item entries or unrelated metadata.
        if not element.tag.startswith("{http://purl.org/dc/elements/1.1/}"):
            continue
        name = element.tag.rsplit("}", 1)[-1].lower()
        if name in ("subject", "description"):
            value = (element.text or "").strip()
            if value:
                fields.setdefault(name, []).append(value)
    subjects = fields.get("subject", [])
    result: dict = {}
    genres = clean_genres(subjects)
    if genres:
        result["genres"] = genres
    if fields.get("description"):
        result["description"] = fields["description"][0]
    for subject in subjects:
        status = STATUS.get(" ".join(subject.split()).casefold())
        if status:
            result["status"] = status
            break
    return result


def read_source_metadata(epub_path: Path) -> dict:
    """Read package metadata without loading any chapter bodies or image data."""
    with ZipFile(epub_path) as archive:
        root = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next((node for node in root.iter() if node.tag.endswith("rootfile")), None)
        package_path = rootfile.get("full-path") if rootfile is not None else None
        if not package_path or package_path.startswith(("/", "../")) or ".." in package_path.split("/"):
            raise ValueError("Missing or unsafe EPUB package path")
        info = archive.getinfo(package_path)
        if info.file_size > 4 * 1024 * 1024:
            raise ValueError("EPUB package metadata is too large")
        return source_metadata_from_package(ET.fromstring(archive.read(package_path)))