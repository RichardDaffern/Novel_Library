#!/usr/bin/env python3
"""Preserve successful novel artefacts even if a bulk GitHub Action fails.

Download-artifact extracts each independent child artefact under
<artifact-name>/<novel-folder>/. This tool validates every complete novel
folder and publishes a recovery artefact containing one ZIP per valid novel
and a manifest of successful, missing and rejected results.

All data comes from the current workflow run. This tool never downloads
novel text or changes the metadata registry. If a job fails, its own
incomplete/partial output is never represented as a completed novel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from tools.download_registry import canonical_url, normalise_range


class RecoveryError(ValueError):
    """Unusable or incomplete child download."""


BOOK_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,199}\Z")
CHAPTER_FILE = re.compile(r"chapter_[0-9]+[.]txt\Z")
MAX_BOOK_BYTES = 850 * 1024 * 1024
MAX_BUNDLE_BYTES = 1_750 * 1024 * 1024


def _book_details(folder: Path, expected: dict) -> tuple[dict, list[dict], set[str]]:
    if folder.is_symlink() or not BOOK_SLUG.fullmatch(folder.name):
        raise RecoveryError("Unsafe novel folder name")
    metadata = folder / "metadata.json"
    manifest = folder / "chapters.json"
    if not metadata.is_file() or not manifest.is_file():
        raise RecoveryError("Missing metadata.json or chapters.json")
    data = json.loads(metadata.read_text(encoding="utf-8"))
    rows = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(rows, list) or not rows:
        raise RecoveryError("Invalid metadata or empty chapter manifest")
    if canonical_url(data.get("source_url", "")) != canonical_url(expected["novel_url"]):
        raise RecoveryError("Novel identity does not match the submitted URL")
    if type(data.get("chapter_count")) is not int or data["chapter_count"] != len(rows):
        raise RecoveryError("Metadata chapter count does not match manifest")
    if len(rows) > 20000:
        raise RecoveryError("Excessive chapter count")
    rng = normalise_range(expected.get("chapter_range", ""))
    if rng != "all":
        first, last = map(int, rng.split("-"))
        if len(rows) != last - first + 1:
            raise RecoveryError("Incomplete selected chapter range")
    else:
        first = 1
    filenames = {"metadata.json", "chapters.json", "source.epub"}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RecoveryError("Invalid chapter record")
        name = row.get("file")
        if (not isinstance(name, str) or
                not CHAPTER_FILE.fullmatch(name) or name in filenames or
                row.get("position") != first + i):
            raise RecoveryError("Duplicate, unsafe or out-of-order chapter file")
        filenames.add(name)
        path = folder / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise RecoveryError("Missing or empty chapter")
        checksum = row.get("sha256")
        if (not isinstance(checksum, str) or len(checksum) != 64 or
                hashlib.sha256(path.read_bytes()).hexdigest() != checksum):
            raise RecoveryError("Invalid chapter SHA-256")
    cover = data.get("cover_image")
    if cover:
        if cover not in ("cover.jpg", "cover.png"):
            raise RecoveryError("Unsupported cover file")
        filenames.add(cover)
    actual_files = {item.name for item in folder.iterdir()}
    if actual_files != filenames:
        raise RecoveryError("Unexpected or missing files in novel folder")
    total_bytes = 0
    for name in filenames:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise RecoveryError("Unsafe or missing member")
        total_bytes += path.stat().st_size
        if total_bytes > MAX_BOOK_BYTES:
            raise RecoveryError("Novel exceeds the 850 MiB recovery safety limit")
    with ZipFile(folder / "source.epub") as epub:
        if epub.testzip() is not None:
            raise RecoveryError("Invalid EPUB ZIP CRC")
    return data, rows, filenames


def recover(plan: dict, artifact_root: Path, output_dir: Path,
            *, run_id: str = "") -> dict:
    """Save every valid complete child artefact in a separate portable ZIP."""
    if output_dir.exists():
        raise RecoveryError("Recovery output already exists")
    groups = plan.get("groups")
    if not isinstance(groups, dict):
        raise RecoveryError("Invalid bulk selection plan")
    scheduled = {
        canonical_url(item["novel_url"]): dict(item, site=site)
        for site, items in groups.items() for item in items
    }
    if not scheduled and not plan.get("skipped"):
        raise RecoveryError("No selected downloads in plan")
    output_dir.mkdir(parents=True)
    recovered = []
    rejected = []
    completed_urls = set()
    used_bytes = 0
    artifact_root = Path(artifact_root)
    artifacts = sorted(artifact_root.iterdir()) if artifact_root.is_dir() else []
    for artefact in artifacts:
        if not artefact.is_dir():
            continue
        if not artefact.name.startswith("novel-"):
            continue
        if run_id and not artefact.name.startswith(f"novel-{run_id}-"):
            continue
        try:
            candidates = list(artefact.iterdir())
            if (len(candidates) != 1 or not candidates[0].is_dir()
                    or candidates[0].is_symlink()):
                raise RecoveryError("Expected exactly one novel directory")
            book = candidates[0]
            try:
                info = json.loads((book / "metadata.json").read_text(encoding="utf-8"))
                url = canonical_url(info["source_url"])
            except (ValueError, KeyError, OSError, TypeError) as exc:
                raise RecoveryError("Cannot determine novel source identity") from exc
            selected = scheduled.get(url)
            if selected is None:
                raise RecoveryError("Not one of this batch's selected novels")
            if url in completed_urls:
                raise RecoveryError("Duplicate complete artefact for the same novel")
            meta, chapters, filenames = _book_details(book, selected)
            filename = "novel-" + hashlib.sha256(
                (url + "\n" + selected.get("chapter_range", "")).encode("utf-8")
            ).hexdigest()[:16] + ".zip"
            dest = output_dir / filename
            if dest.exists():
                raise RecoveryError("Duplicate recovery file identity")
            with ZipFile(dest, "w", compression=ZIP_DEFLATED, compresslevel=6) as z:
                for name in sorted(filenames):
                    z.write(book / name, arcname=f"{book.name}/{name}")
            with ZipFile(dest) as z:
                if z.testzip() is not None or len(z.namelist()) != len(filenames):
                    raise RecoveryError("Recovery ZIP integrity check failed")
            size = dest.stat().st_size
            if used_bytes + size > MAX_BUNDLE_BYTES:
                dest.unlink()
                raise RecoveryError(
                    "Bulk recovery bundle size limit reached; original child "
                    "artefact remains independently downloadable"
                )
            used_bytes += size
            completed_urls.add(url)
            recovered.append({
                "url": url, "title": meta.get("title", ""),
                "site": selected["site"], "chapters": len(chapters),
                "filename": filename, "source_artifact": artefact.name,
            })
        except (RecoveryError, ValueError, OSError, BadZipFile, KeyError, TypeError) as exc:
            # Reject only this artefact. Other successful downloads survive.
            rejected.append({"artifact": artefact.name, "reason": str(exc)})
            print(f"RECOVERY_SKIPPED {artefact.name}: {exc}", flush=True)
            # Clean up an incomplete ZIP that failed its own checks.
            if 'dest' in locals() and isinstance(dest, Path) and dest.exists():
                dest.unlink()
            dest = None
    missing = [
        {"url": url, "site": item["site"], "title": item.get("title", "")}
        for url, item in scheduled.items() if url not in completed_urls
    ]
    report = {
        "version": 1,
        "selected": plan.get("selected_count", len(scheduled)),
        "recovered": recovered,
        "missing_or_failed": missing,
        "already_available": plan.get("skipped", []),
        "rejected_artifacts": rejected,
    }
    (output_dir / "bulk_recovery_manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = [
        "## Bulk recovery artefact",
        "",
        f"Successfully saved: **{len(recovered)}** novel ZIP(s).",
        f"Missing or failed: **{len(missing)}** selected download(s).",
        f"Rejected archive(s): **{len(rejected)}**.",
        f"Already available from previous runs: **{len(plan.get('skipped', []))}**.",
        "",
        "One ZIP per recovered novel is included alongside the JSON manifest.",
        "Each child workflow's original successful artefact also remains",
        "independently available for its normal seven-day retention period.",
        "No failed or incomplete book is labelled complete.",
    ]
    (output_dir / "README.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary), flush=True)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("recovery_output"))
    p.add_argument("--run-id", default="")
    options = p.parse_args(argv)
    try:
        plan = json.loads(options.plan.read_text(encoding="utf-8"))
        report = recover(plan, options.artifacts, options.output,
                         run_id=options.run_id)
    except (ValueError, OSError, KeyError, TypeError, BadZipFile) as exc:
        print(f"Bulk recovery preparation failed: {exc}", file=sys.stderr)
        return 1
    total = len(report["recovered"])
    target = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as file:
            file.write(f"## Bulk partial recovery\n\n")
            file.write(f"Recovered **{total}** verified completed novels into separate ZIP files.\n")
            file.write("Original successful per-novel artefacts remain downloadable.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
