# WebNovel Local Import V2: bulk EPUB/TXT from saved chapters

This tool supports **authorised, locally saved** HTML, HTM, and TXT chapters.
It never downloads from WebNovel, uses no login/session cookies, and does not
interact with Cloudflare. NovelFull and the older two-chapter importer stay
unchanged.

## What is new

- Bulk import up to **10,000 consecutive saved chapters** from one local folder.
- Automatically identify the chapter number and title in browser filenames
  such as Novel Chapter 2 - Chapter 2_ The Adventure - WebNovel.html.
- Sort numerically (Chapter 2 comes before Chapter 10).
- Reject missing numbers, duplicates, conflicting filename numbers, missing
  text, and recognised locked chapter bodies.
- Optional inclusive chapter range (--chapter-range 100-200).
- Write separate numbered TXT chapters, combined book.txt, book.epub, and
  metadata.json.
- Report progress for each chapter.
- Keep .webnovel-import-state.json with hashes so interrupted local imports
  can be resumed safely using --resume.
- Use --dry-run to validate filename order, missing chapters, and duplicates
  without generating any files or reading story text.

## Windows PowerShell: try the two saved chapters

From the Novel_Library repository:

~~~powershell
git pull

python -m tools.webnovel_bulk_import `
  --input-dir "C:\Aditya Sreevatsa K\Entertainment\Novels" `
  --output-dir "C:\Aditya Sreevatsa K\Entertainment\Novels\WebNovel-Exports\Platinum-Dragon-Wizard" `
  --book-title "Harry Potter: Platinum Dragon Wizard" `
  --author "BlurryPinkSnake" `
  --chapter-range 1-2 `
  --confirm-rights `
  --dry-run
~~~

When the preview shows chapters 1 and 2 in order, **run the same command
without --dry-run**. Output is saved outside the Git repository; do not
upload these chapter texts to GitHub.

If the selected input folder contains other unrelated .html or .txt
files, move the chapters for one novel into a dedicated folder and point
--input-dir to it. Only direct files are scanned, not subfolders. The
importer deliberately rejects non-chapter filenames rather than silently
ignoring possible missing chapter content.

## Full saved novel

Save all authorised readable chapters in the same dedicated folder. Then omit
--chapter-range to include the consecutive chapters from the lowest numbered
file through the highest. For a subset, use --chapter-range 1-50 or
--chapter-range 100-200. A gap in the selected range is an error, not an
instruction to fetch a chapter online.

There is no requirement to start at chapter 1 if you import a higher range.
The source .html, .htm, and .txt files must include unambiguous chapter
numbers in their filenames.

## Resume after interruption

Keep your input files and output folder unchanged, then repeat the same
command with --resume. Completed chapter TXT files are verified against
checksums of both their sources and outputs, then reused; any remaining
chapters are processed. Finally the EPUB and combined TXT are assembled.

If a previously completed source or generated TXT changed, resume will
refuse to combine mismatched material. Start again with a **new empty output
directory** instead. Without --resume, the importer refuses to overwrite
a nonempty output directory.

If a chapter is locked or its page body is unavailable, the run stops with
a chapter-numbered error. The importer does not unlock content, attempt
network access, or silently insert a blank chapter.

## Outputs

- chapter-000001.txt, chapter-000002.txt, etc. (actual chapter numbers)
- book.txt
- book.epub (EPUB2 with per-chapter navigation entries)
- metadata.json (chapter order and original filenames)
- .webnovel-import-state.json (local resume metadata; no chapter text)

The parser requires locally readable saved chapter text and rejects unknown
HTML body layouts. A successful import and a valid EPUB archive do not
independently prove every word matches the original page; visually inspect
the EPUB before importing hundreds of chapters.

## Offline testing

~~~powershell
python -m unittest tests.test_webnovel_bulk_import -v
~~~

All repository unit tests run on Linux and Windows CI with synthetic prose
only. No live WebNovel requests or chapter text are published.
