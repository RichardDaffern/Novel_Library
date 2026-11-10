# PDF-to-Novel: double-click converter (Windows)

The directory is called `PDF-to-Novel` because Windows does not permit `>` in
folder names (`PDF->Novel` would be invalid).

## Use

1. Copy your locally saved, authorised `.pdf` books into **`PDFs/`**.
2. Double-click **`Convert-PDFs.cmd`** from this folder.
3. Confirm you are permitted to archive the PDFs.
4. Find completed **`novel-*.zip`** archives in **`Novels/`**, along with separate
   `*-validation.json` reports. The ZIPs are ready for review before using the
   existing private dataset uploader. The script does **not** upload anything.

The CMD finds Python 3 (`py -3`, then `python`) and installs local dependencies
from `../requirements-pdf.txt` only when missing. You need Python and an internet
connection for *first-time dependency installation*; conversions themselves are
offline. Any number of PDFs can be placed in `PDFs/`, including filenames with
spaces. Existing validated ZIPs are **skipped**, not overwritten. Corrupt ZIPs
are reported as failures and left untouched. PDFs are never modified or deleted.

If a PDF cannot be reliably split into chapters, it is **not** published as a ZIP.
When possible, the program saves a `<PDF filename>-chapter-plan.json` review
suggestion in `Novels/`. Review/edit that JSON and copy it beside your input PDF
as `PDFs/<PDF filename without .pdf>.chapters.json`, then rerun. If the PDF is
image-only or has nonstandard layout, see `../docs/PDF_TO_NOVEL.md`.

Note: when a ZIP is already present and you intentionally want a new conversion
using a revised chapter plan, **move the old ZIP out of `Novels/`** before
running the CMD again. Nothing is overwritten automatically.

## GitHub storage policy

Both `PDFs/` and `Novels/` are tracked as empty directories using `.gitkeep`.
Their `.gitignore` rules prevent personal PDF files, generated novels, manual
chapter plans and extraction reports from being committed accidentally.

## Advanced, noninteractive command

From the repository root:

```powershell
py -3 -m tools.pdf_batch --confirm-rights
```

The program accepts `--pdf-dir` and `--output-dir` for custom directories.