# Novel Library

Local-first novel downloader built using FanFicFare. Produces numbered UTF-8 TXT chapters, an EPUB, a JSON chapter manifest and chapter-completion percentages.

**Only download and store material you are permitted to archive.** This project does not circumvent source-site access controls. Do not publicly distribute copyrighted chapter text without permission. Novel text and EPUBs are **not** checked into this Git repository.

## Run locally

Install Python 3.12 and the dependencies:

~~~powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
~~~

Test the download-to-EPUB pipeline without external network requests:

~~~powershell
python novel_downloader.py --self-test --chapter-range 1-2
~~~

For material you are authorised to download, use a supported HTTPS URL:

~~~powershell
python -u novel_downloader.py "https://example.org/novel" --confirm-rights
python -u novel_downloader.py "https://example.org/novel" --confirm-rights --chapter-range 1-30
~~~

Chapter ranges are one-based, inclusive positions in the site's chapter index. The script prints a chapter-completion percentage and writes a TXT file into the chapters_in_progress directory as soon as each chapter finishes. After successful EPUB creation, it exports the final chapters, manifest and metadata and removes temporary checkpoints.

## GitHub Actions: NovelFull - Download

The NovelFull single-download workflow uses FanFicFare. The separate `CI` workflow runs automatic regression checks and is not a downloadable-novel action.

In **Actions > NovelFull - Download > Run workflow**, enter:

- **Novel URL**: the source URL
- **Chapter range**: optional, e.g. 1-30; blank requests the whole novel
- **Force**: defaults to **off**; select it to bypass the downloaded-novel registry

There is no permission-confirmation checkbox in the Actions form; the workflow passes the script's local --confirm-rights flag internally. Only run authorised downloads.

The workflow checks downloaded_novels.json **before downloading chapters**. It then discovers the full chapter count and divides the requested range into automatically managed batches of **up to 200 chapters**, with **1 to 6 concurrent chapter-download jobs**, calculated from the selected chapter count: one worker per 600 chapters (rounded up), never more than six or the available number of batches. Each batch has its own timeout, so a 4,000-chapter novel is no longer limited by a single 170-minute process. A rerun automatically **reuses complete verified batch artifacts** that have not expired, and downloads only missing or failed batches unless Force is selected. If a batch times out, its temporary chapter checkpoints are uploaded separately, but the incomplete batch is retried on the next run. No partially downloaded book is registered as complete. A completed download is treated as available only while its GitHub Actions artifact has not expired. A full-novel entry covers all smaller ranges; combined completed ranges can also cover a requested range. If already available, the workflow exits successfully with an **Already downloaded** notice. Force bypasses that check. Different novel URLs can run in separate workflows concurrently. Duplicate runs for the same URL queue instead of interrupting an active download. Each completed novel's registry PR is regenerated from the latest `main` and retried on merge conflicts, so simultaneous novels do not overwrite each other's records.

When all batches are complete, an assembly job verifies every selected chapter position, creates **one complete EPUB** and numbered TXT collection, and uploads them as a final artifact retained for **seven days**. Verified intermediate batches also have seven-day retention. The first run using the new workflow cannot automatically reuse the checkpoints from the older, pre-chunking timeout run. The novel content is not committed to the repository. Partial checkpoints may also be uploaded when downloads fail.

After uploading and validating the output, the workflow:

1. Adds the download metadata, range, chapter count, run link and artifact-expiry information to downloaded_novels.json.
2. Regenerates [DOWNLOADED_NOVELS.md](DOWNLOADED_NOVELS.md), the human-readable index.
3. Regenerates the registry from the latest `main`, then creates a per-novel registry branch and pull request.
4. Attempts to **squash-merge that metadata-only PR into main** automatically; concurrent PR conflicts trigger a fresh registry build and another merge attempt.

For automatic PR creation and merging, the repository owner must enable **Settings > Actions > General > Workflow permissions > Allow GitHub Actions to create and approve pull requests**. The workflow token also needs contents and pull-requests write access, configured in the workflow. Without the repository setting, GitHub rejects PR creation even with YAML write permissions. The chapter/EPUB artifact remains downloadable, and the metadata-only branch is retained with a manual PR link in the job summary. Branch protection requiring approvals or status checks can also prevent automatic merging.

**Important:** Your repository is currently public. GitHub Actions artifacts may be accessible to other users of public repositories. Making a repository private limits exposure but does not grant permission to redistribute copyrighted content.

## GitHub Actions: Library - Bulk Download

Use **Actions > Library - Bulk Download > Run workflow** for downloads from
both supported websites. The workflow groups download jobs by website,
without changing the individual site-specific downloaders.

- **Website group:** All, NovelFull or FreeWebNovel.
- **Saved novel names:** Type names listed in
  [DOWNLOADED_NOVELS.md](DOWNLOADED_NOVELS.md), separated by commas or
  semicolons. Example: `The World Online; The First Order`. Use semicolons
  when a novel's title itself contains a comma.
- **New novel URLs:** Optionally supply HTTPS source URLs for books not yet
  recorded. Names and URLs can be mixed.
- **Chapter range:** Optional; blank requests a whole novel.
- **Force:** Redownload even if a completed artifact is still available.

GitHub Actions lacks a dynamic multi-select field, so saved names are entered
as multi-value text rather than selected with checkboxes. Example: select
NovelFull and enter `True Martial World; The World Online`. The planner
resolves their saved URLs automatically. To list recognised titles, run:

~~~powershell
python -m tools.library_bulk list
~~~

Titles come from the completed-download registry and
[novel_sources.json](novel_sources.json), a small curated list seeded with
the tested FreeWebNovel example. For a brand-new title, enter its exact URL;
after a successful download and registry update, that title is available by
name. You can also add a title/URL to the curated JSON list beforehand.

Unknown or ambiguous titles, URLs from an unsupported or mismatched site,
and more than **10 distinct novels** are rejected before any downloading.
Already-available books are skipped unless Force is selected. Up to three
NovelFull books and two FreeWebNovel books can run concurrently; the source
downloaders still enforce their own chapter limits. Each book produces its
own ZIP artifact, with metadata-only registry updates for completed books.

`DOWNLOADED_NOVELS.md` is grouped by website automatically. Historical
downloads retain all their artifact links and chapter counts, including
expired artifacts. Only archive content you are authorised to store. In a
public repository, GitHub Actions artifacts may be accessible to others.

## GitHub Actions: FreeWebNovel

FreeWebNovel is a separate source, not a FanFicFare adapter. The existing
NovelFull actions are unaffected. Its public Chapter 1 and 2 retrieval was
verified locally against the novel **The First Order** on 10 November 2026.
A completed whole-book FreeWebNovel download remains unverified until the
dedicated Actions workflows are run against the live site.

**FreeWebNovel - Download** handles one book. Use **Library - Bulk Download** for multiple titles across either website, optionally by saved novel names.

Use book URLs such as:

~~~text
https://freewebnovel.com/novel/the-first-order
~~~

The workflows divide chapters into **50-chapter batches**, download each
batch sequentially with a one-second interval between public chapter
requests, and allow at most two simultaneous batches per book. Every
chapter's text, position and checksum must be present before a finished
EPUB is assembled. Failed or missing chapters stop the batch; the book
is never registered as complete. Intermediate chapter-range artifacts
can be reused when their retention has not expired. Output uses the
same \`source.epub\`, numbered UTF-8 chapter text, JSON manifests and
ZIP-artifact conventions as NovelFull. Successful metadata is published
to the existing download registry without committing novel text.

Only request books you have permission to archive. This adapter does not
access locked pages or bypass access restrictions, and it does not
automatically retry HTTP denials. Site changes or non-consecutive
chapter numbering may stop a full-book download rather than produce a
silently incomplete archive. In a **public** GitHub repository, Actions
artifacts may be accessible to others; private books and permissions
must be considered before uploading.

For a small local test (from the repository root):

~~~powershell
python -m tools.freewebnovel_downloader "https://freewebnovel.com/novel/the-first-order" --chapter-range 1-2 --output-dir freewebnovel-test --confirm-rights
~~~

The standalone downloader supports batches of at most 100 chapters.
The Actions workflow handles partitioning for longer novels.

## WebNovel compatibility feasibility (separate, metadata-only)

WebNovel is **not yet supported as a chapter-download source**. Its public
`/book/` pages can expose a title, author and listed chapter count, but this
does not establish permission or technical support for exporting chapter text.
WebNovel's terms restrict reproduction and circumventing access controls;
locked/premium chapters and authentication are deliberately unsupported.

A separate, read-only metadata probe lives in
[`tools/webnovel_probe.py`](tools/webnovel_probe.py), independent of
`novel_downloader.py` and the NovelFull GitHub workflows.

Run a one-page public-book metadata check (no login, chapter requests or text exports):

~~~powershell
python -m tools.webnovel_probe "https://www.webnovel.com/book/22196546206090805"
~~~

The probe makes one normal HTTPS request to the public book page and prints
JSON containing the available book metadata and
`"chapter_export_verified": false`. If the site blocks automated access
or changes its page layout, the probe fails without bypassing restrictions.
You can test the parser offline using a supplied HTML fixture via
`--html-file book.html`. No WebNovel chapter files or EPUBs are produced.

WebNovel's own reading app may offer an **in-app offline download** for
eligible chapters. In-app caching is different from an authorised EPUB/TXT
export. A standalone chapter-export adapter would require an approved
source/permission and a separate implementation and validation process.

## Synopsis metadata in EPUB and ZIP archives

NovelFull's FanFicFare adapter reads each book's public description and can
store it in the source EPUB as `dc:description`. The download pipeline now
preserves this information through chapter-range exports and the final
reassembled EPUB. Both `source.epub` and `metadata.json` include the
description; the JSON also offers a `synopsis` alias for library readers.
Books whose source does not supply a description are left blank rather than
given fabricated text. The preservation fix applies to **newly created**
download artifacts; it does not rewrite existing GitHub artifacts.

To repair downloaded ZIPs **without downloading any chapters again**, use
the separate `tools/repair_synopsis.py` command. It checks whether the
existing ZIP's EPUB or metadata already contains a synopsis. Otherwise, it
can fetch the description from the public NovelFull **book information**
page only (no chapter requests, login, challenge bypass or retries).
It adds `dc:description` to the embedded EPUB and `description` plus
`synopsis` to the JSON. Chapter TXT files and manifests are unchanged.

First check a single ZIP:

~~~powershell
python -m tools.repair_synopsis --zip "Downloaded_Novels/novel-123.zip"
~~~

Repair one ZIP using its public NovelFull book synopsis:

~~~powershell
python -m tools.repair_synopsis --zip "Downloaded_Novels/novel-123.zip" --apply
~~~

Or repair every valid novel ZIP in your downloaded directory:

~~~powershell
python -m tools.repair_synopsis --directory "Downloaded_Novels"
python -m tools.repair_synopsis --directory "Downloaded_Novels" --apply
~~~

The default is a **dry run**. With `--apply`, the repair script
builds a replacement ZIP in the **same directory**, verifies all ZIP/EPUB
integrity checks, confirms every chapter and manifest remains byte-identical,
flushes the temporary file and **atomically replaces the original ZIP**.
On validation, permission or network failure, the original ZIP remains
unchanged; temporary files are cleaned up. It does **not** download chapters
again or create a duplicate `Synopsis_Repaired` directory.

This is a safe replacement, not a permanent backup: if you want an undo
copy, keep one separately. The script still supports an explicit
`--output-dir "some-folder"` to create repaired copies instead.

If you already have a custom synopsis or the public source is unavailable,
pass `--description-file "summary.txt"` with a single `--zip` and `--apply`.
The importer in your reading app may require you to replace or reimport
the previously imported novel: repairing your local ZIP does not
retroactively change hosted/library data.

Only archive and update material you are authorised to keep. Source
descriptions may be unavailable or blocked; failed books are reported and
their original ZIPs remain untouched.

## Windows: one-click download of completed archives

The [Download-All-Novels.cmd](Download-All-Novels.cmd) launcher retrieves the already-created, **full-novel** GitHub Actions artifacts listed in [downloaded_novels.json](downloaded_novels.json). It does **not** download chapters from source websites or trigger new Actions runs.

1. Install [GitHub CLI](https://cli.github.com/) (for example, `winget install --id GitHub.cli --exact`).
2. If GitHub CLI is already signed into an account with repository read access, keep using it. You do **not** have to use the account that owns the repository. Otherwise, the launcher offers a browser-based sign-in.
3. Clone the repository or run `git pull` to get the latest files.
4. Double-click `Download-All-Novels.cmd` from the repository root. The window stays open at the end, including on errors.

The launcher saves a detailed local diagnostic transcript to `download-last-run.log` and shows the actual exit code. The log is ignored by Git and is overwritten on each run. If GitHub CLI needs authentication, choose **Y** when prompted; `gh auth login --web --clipboard --skip-ssh-key` shows a one-time device code and opens a browser to authorise the account you choose. You can also request a browser login explicitly with `Download-All-Novels.cmd -BrowserLogin`. This is an ordinary stored GitHub CLI login, **not** an automatically expiring temporary session. If you add a different account, use `gh auth switch -u AdityaSreevatsaK` to return to your original account or `gh auth logout -u ACCOUNT_NAME` to remove the added login. Avoid sharing your login tokens or diagnostic logs publicly.

Each completed novel is saved as a single `novel-<artifact-id>.zip` in the ignored `Downloaded_Novels/` directory, with a single book folder inside containing `chapter_XXXX.txt`, `chapters.json`, `metadata.json`, and `source.epub`. The downloader checks the book's source URL, manifest and EPUB before saving; unrelated folders in bulk artifacts (including the older Abe the Wizard artifact) are not included. The script reads the **current** index, identifies each novel by its source URL and checks existing ZIP files **before downloading**. A valid local copy is skipped even when its filename or GitHub artifact ID differs from the current registry. Missing or invalid ZIPs can still be retrieved; an invalid existing file is never overwritten. GitHub CLI authentication is only requested when a novel actually needs downloading. Unavailable/expired artifacts are reported in `Downloaded_Novels/failed-downloads.txt`. It cannot resurrect expired artifacts, and it does not bypass access controls. GitHub artifacts normally expire after seven days, so download promptly.

By default, the local duplicate check searches ZIP files in `Downloaded_Novels/`. If you also have ZIPs in another directory (for example, your bulk-uploader's `novels` folder), pass that directory to avoid downloading copies of those books too:

~~~cmd
Download-All-Novels.cmd -ExistingZipDirectory "C:\\Path\\To\\Other\\Novels"
~~~

Only verified, full-novel ZIPs count as present. The script checks ZIP contents, chapter manifest, EPUB and the book's source URL; it doesn't rely on filenames alone. The other directory is not modified. It does not scan arbitrary folders on your computer.

If you already downloaded novels with the older folder-based downloader, **do not download them again**. Repackage the local files into verified book ZIPs using:
 
~~~cmd
Download-All-Novels.cmd -RepackOnly
~~~

This mode does not require GitHub CLI or re-download any artifacts. It moves each successfully repacked original folder to `Downloaded_Novels_Originals/` (outside the ZIP directory) as a recoverable backup. The ZIP directory contains one ZIP per successful novel. After checking your ZIPs, you can manually remove the backup folder to reclaim disk space. If a book cannot be validated, its original folder is left untouched and reported in `failed-downloads.txt`. The ZIP filenames use unique artifact IDs because different books can share a single workflow run ID. For existing folder backups, the full multi-book artifact is preserved while only the expected book is placed in its ZIP.

To verify the Windows launcher can resolve its folders without signing in or downloading anything:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\\tools\\download_all_artifacts.ps1 -CheckSetup
~~~

For a quick one-book smoke test (after authenticating):

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\download_all_artifacts.ps1 -Limit 1
~~~

To save to another folder, use `-Destination 'D:\Novels'`. You can rerun the command after a network interruption; it skips verified local ZIPs and repacks older complete folders before attempting new downloads. You must have the right to archive the underlying material. Novel contents are never committed to the repository.

## Downloaded-novel list

View [DOWNLOADED_NOVELS.md](DOWNLOADED_NOVELS.md) for completed downloads. The index includes previously verified completed jobs, including the recovered Abe the Wizard entry from bulk run 42393126629. The registry is an index, **not permanent storage**: once an artifact expires, a normal rerun is allowed so the book can be archived again, subject to permission.

## Other tests

The CI workflow verifies two synthetic chapters on Linux and Windows. A separate probe has confirmed that FanFicFare can retrieve and parse two real NovelFull chapter bodies, but it does not retain their text. Do not confuse retrieval tests with authorisation to publish those chapters.
