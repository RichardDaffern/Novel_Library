#!/usr/bin/env python3
"""Batch-convert user-supplied PDFs without altering original PDFs or other downloaders.

The Windows launcher is PDF-to-Novel/Convert-PDFs.cmd. This module also runs on
Linux/macOS for offline testing: python -m tools.pdf_batch --confirm-rights
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import sys
from zipfile import BadZipFile, LargeZipFile

from tools.pdf_to_novel import ConversionError, analyse, convert, validate_zip

REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PDFS = REPOSITORY / "PDF-to-Novel" / "PDFs"
DEFAULT_NOVELS = REPOSITORY / "PDF-to-Novel" / "Novels"


def _pdf_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspection_plan(pdf: Path, output_dir: Path, report=print) -> None:
    """Offer a per-PDF editable plan only if automatic inspection is possible.

    Do not change or overwrite a previously generated plan. A plan must be
    reviewed, then copied to PDFs/<same-name>.chapters.json to be applied.
    """
    import json

    try:
        _, chapters, _ = analyse(pdf, progress=lambda _: None)
    except (ConversionError, OSError, ValueError):
        report("  Chapter detection requires manual inspection; no plan could be generated.")
        return
    proposed = output_dir / (pdf.stem + "-chapter-plan.json")
    if proposed.exists():
        report(f"  Existing review plan preserved: {proposed}")
        return
    proposed.write_text(json.dumps({"chapters": chapters}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    report(f"  Review plan saved: {proposed}")
    report(f"  To apply it, edit and copy it to: {pdf.with_suffix('.chapters.json')}")


def batch_convert(pdf_dir: Path, output_dir: Path, *, confirm_rights: bool = False,
                  report=print) -> dict[str, int]:
    """Convert all PDFs; never overwrite a ZIP or touch the source PDFs."""
    if not confirm_rights:
        raise ConversionError("Confirm you are permitted to archive the supplied PDFs")
    pdf_dir, output_dir = Path(pdf_dir), Path(output_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted((p for p in pdf_dir.iterdir() if p.is_file() and p.suffix.casefold() == ".pdf"),
                  key=lambda p: (p.name.casefold(), p.name))
    summary = {"found": len(pdfs), "converted": 0, "skipped": 0, "failed": 0}
    report(f"Input PDFs: {pdf_dir}")
    report(f"Output novels: {output_dir}")
    if not pdfs:
        report("No PDF files found. Copy your PDFs into the PDFs folder and run the CMD again.")
        return summary

    for index, pdf in enumerate(pdfs, 1):
        report(f"\n[{index}/{len(pdfs)}] {pdf.name}")
        archive = None
        try:
            archive = output_dir / ("novel-" + _pdf_sha256(pdf)[:12] + ".zip")
            if archive.exists():
                # A corrupted existing archive is an error, not a reason to overwrite.
                validate_zip(archive)
                summary["skipped"] += 1
                report(f"  SKIP: already converted and validated: {archive.name}")
                continue
            boundaries = pdf.with_suffix(".chapters.json")
            if not boundaries.is_file():
                boundaries = None
            elif boundaries.is_dir():
                raise ConversionError(f"Manual chapter plan is not a file: {boundaries}")
            target, validation = convert(pdf, output_dir, boundaries=boundaries,
                                         progress=lambda msg: report("  " + msg))
            summary["converted"] += 1
            report(f"  OK: {target.name}")
            report(f"  Validation report: {validation.name}")
        except (ConversionError, OSError, ValueError, KeyError, BadZipFile, LargeZipFile) as exc:
            summary["failed"] += 1
            report(f"  FAILED: {exc}")
            if archive is None or not archive.exists():
                _inspection_plan(pdf, output_dir, report=report)
            else:
                report("  Existing ZIP preserved. Move it away before retrying.")
    report("\nSummary: {found} PDF(s), {converted} converted, {skipped} already done, "
           "{failed} failed.".format(**summary))
    if summary["failed"]:
        report("Check the failure messages and review chapter boundaries before retrying.")
    report("No files were uploaded to GitHub or Hugging Face.")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDFS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_NOVELS)
    parser.add_argument("--confirm-rights", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = batch_convert(args.pdf_dir, args.output_dir, confirm_rights=args.confirm_rights)
        return 1 if summary["failed"] else 0
    except (ConversionError, OSError, ValueError) as exc:
        print(f"Batch conversion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())