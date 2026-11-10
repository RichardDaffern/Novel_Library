# PDF to Novel Library ZIP

This is an offline converter for locally supplied, authorised PDFs. It never uses
networking, OCR, GitHub Actions downloads, or Hugging Face upload services. It does
not change any existing downloader or registry code.

## Install (Windows PowerShell or Command Prompt)

From the cloned repository root:

```powershell
py -3 -m pip install -r requirements-pdf.txt
```

## Inspect chapters before publishing

```powershell
py -3 -m tools.pdf_to_novel "C:\Books\Novel.pdf" --inspect --output-dir "C:\Books\Converted"
```

This creates `pdf-chapter-plan.json` with one-based source page and nonempty line
indices. If needed, edit the `title`, `number`, `page`, `line`, or `heading_lines`
fields. `heading_lines` is the number of visually styled heading lines to skip
from the body. Do not change it to include story text. Pass the inspected plan
using `--boundaries` for a corrected conversion. Source headings that were
changed are recorded in the validation report.

## Convert and validate

```powershell
py -3 -m tools.pdf_to_novel "C:\Books\Novel.pdf" --boundaries "C:\Books\Converted\pdf-chapter-plan.json" --expected-chapters 22 --output-dir "C:\Books\Converted" --confirm-rights
```

For PDFs with reliable headings, omit `--boundaries`. Override missing metadata
using `--title`, `--author`, `--language`, or a sourced `--description`.
Use `--replace` only to intentionally overwrite an existing ZIP with the same
PDF SHA-256 identity. The source PDF is never modified. `--inspect` requires
`--replace` to overwrite an existing chapter plan.

ZIP filenames are `novel-<PDF SHA256 prefix>.zip` and contain exactly one folder,
`<title-slug>/`, holding `metadata.json`, `chapters.json`,
`chapter_0001.txt` etc., `source.epub`, and optional `cover.jpg`.
Each TXT chapter contains the title, blank line, then body, encoded as UTF-8
with LF newlines. `chapters.json` uses the original downloader's position,
chapter_number, title, file, word_count, and sha256 fields. `source_url`
is a stable *local identity*, `pdf://sha256/<sha256>`, not a website.

A sibling `novel-<hash>-validation.json` includes the PDF page count,
source chapter boundaries, manual corrections, source-line coverage counts,
source hash, short-chapter flags, structural/EPUB checks, and warnings. Review
this report and read the first/last and selected interior chapters before
uploading the ZIP through your existing private dataset uploader. The report
is not inside the ZIP.

## Limitations and review requirements

- Selectable-text PDFs only. Image-only PDFs fail closed and require a separately
  reviewed OCR workflow. This utility does not try to bypass protections.
- A source typo stays a source typo unless you explicitly correct its title in
  the boundaries plan. The converter does not invent or rewrite novel prose.
- The PDF's reliable font and paragraph-indentation layout is used; multi-column,
  unusual layouts, headers, footers, tables, and inconsistent heading typography
  may need manual review and additional extraction rules before conversion.
- Ligature glyphs (such as `ﬁ`) are expanded to ordinary letters, without
  applying broad Unicode compatibility normalisation to Chinese text.
- Body lines are assigned exactly once after the first chapter heading. Front
  matter before that heading is omitted and counted in the report.
- An absent synopsis is not invented. Reformatting cannot repair grammatical
  mistakes already present in the input PDF.
- The conversion validates its *own* ZIP format. Final end-to-end compatibility
  with a separately maintained dataset uploader must also be tested there.

Run offline unit tests: `py -3 -m unittest discover -s tests_pdf -p test_pdf_to_novel.py -v`.