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

The workflow checks downloaded_novels.json **before downloading chapters**. A completed download is treated as available only while its GitHub Actions artifact has not expired. A full-novel entry covers all smaller ranges; combined completed ranges can also cover a requested range. If already available, the workflow exits successfully with an **Already downloaded** notice. Force bypasses that check. Workflows are serialised to avoid conflicting registry updates.

Successful runs save the actual EPUB and TXT chapter files as a GitHub Actions artifact, retained for **seven days**. The novel content is not committed to the repository. Partial checkpoints may also be uploaded when downloads fail.

After uploading and validating the output, the workflow:

1. Adds the download metadata, range, chapter count, run link and artifact-expiry information to downloaded_novels.json.
2. Regenerates [DOWNLOADED_NOVELS.md](DOWNLOADED_NOVELS.md), the human-readable index.
3. Creates a registry/download-<run id> branch and pull request.
4. Attempts to **squash-merge that metadata-only PR into main** automatically.

For automatic PR creation and merging, the repository owner must enable **Settings > Actions > General > Workflow permissions > Allow GitHub Actions to create and approve pull requests**. The workflow token also needs contents and pull-requests write access, configured in the workflow. Branch protection requiring approvals or status checks can prevent immediate merging; an unmerged PR will remain available for review. The artifact is uploaded even if the registry PR subsequently fails.

**Important:** Your repository is currently public. GitHub Actions artifacts may be accessible to other users of public repositories. Making a repository private limits exposure but does not grant permission to redistribute copyrighted content.

## Downloaded-novel list

View [DOWNLOADED_NOVELS.md](DOWNLOADED_NOVELS.md) for completed downloads. The initial index includes three previously verified completed jobs. The registry is an index, **not permanent storage**: once an artifact expires, a normal rerun is allowed so the book can be archived again, subject to permission.

## Other tests

The CI workflow verifies two synthetic chapters on Linux and Windows. A separate probe has confirmed that FanFicFare can retrieve and parse two real NovelFull chapter bodies, but it does not retain their text. Do not confuse retrieval tests with authorisation to publish those chapters.
