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

## GitHub Actions: Download novel

In **Actions > Download novel > Run workflow**, enter:

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

## GitHub Actions: Bulk Download Novels

Use **Actions > Bulk Download Novels > Run workflow** and enter up to 10 distinct authorised novel URLs separated by commas, spaces or newlines. You may specify one inclusive chapter range for all novels and use Force to bypass the existing-archive check.

The bulk workflow checks the downloaded-novels registry once, removes duplicate URLs and **calls the same automatic chunked downloader for each outstanding novel**. Up to **three distinct novels run concurrently**. Each novel independently scales from **one to six chapter jobs** based on its selected chapter count. This can mean up to **18 chapter download jobs** within one bulk run, subject to GitHub runner availability and source-site limits. Previously recorded completed novels are still skipped when their artifacts are available. A failed novel does not prevent later novels from running.

**Each completed novel has its own EPUB/TXT ZIP artifact within the bulk workflow run**, rather than a combined batch ZIP. Each novel updates the Markdown/JSON index through its own conflict-safe metadata-only pull request. Concurrent unrelated single-novel workflows are also permitted. All artifacts are retained for seven days. Individual verified chapter-range artifacts can be reused on retry, unless Force is selected.

The overall bulk workflow reports failure if any novel fails; completed novels and their downloadable artifacts remain available. The workflows do not publish novel text or EPUBs in Git, and only authorised downloads should be submitted.


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
