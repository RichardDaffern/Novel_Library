# Novel Library

A Python toolkit for downloading **authorised** web novels, assembling complete EPUBs and numbered UTF-8 TXT chapters, and packaging them into validated novel ZIP archives. Includes GitHub Actions download workflows, a Windows artefact downloader, and offline PDF/EPUB conversion.

## Websites and download support

**Full-novel website downloading is implemented for these two sources:**

| Website | Download support | How to use |
| --- | --- | --- |
| [NovelFull](https://novelfull.com/) | **Yes**, using FanFicFare and verified chapter batches | **NovelFull - Download** or **Library - Bulk Download** |
| [FreeWebNovel](https://freewebnovel.com/) | **Yes**, for accessible public chapters, with chapter-by-chapter validation | **FreeWebNovel - Download** or **Library - Bulk Download** |

Other sources have restricted or specialised options, not general-purpose website downloaders:

| Website | Current capability |
| --- | --- |
| [Scribble Hub](https://www.scribblehub.com/) | **One verified author cross-post** (series `445037`) can be fetched automatically via FicHub; other series require offline EPUB import or separate verification. Direct Scribble Hub requests remain blocked |
| [WebNovel](https://www.webnovel.com/) | Limited public-page tests and offline import of chapters you have saved with permission; no full website downloader |
| [Royal Road](https://www.royalroad.com/) | Offline conversion of an already-authorised local EPUB; no enabled site-download workflow |
| [WTR-Lab](https://wtr-lab.com/) | Offline conversion of an already-authorised local EPUB; no enabled site-download workflow |
| [Novel Fire](https://novelfire.net/) | Offline feasibility checks only; no website downloader |
| [Light Novel Pub](https://lightnovelpub.com/) | Offline feasibility checks only; no website downloader |

**[Website support guide](docs/WEBSITE_SUPPORT.md)** explains the supported URL formats, download limits, available workflows, current verification level and restrictions for **each** site. A working tool does not guarantee that a source currently permits or serves every novel.

## Download a novel with GitHub Actions

Go to [Actions](https://github.com/RichardDaffern/Novel_Library/actions) and run the appropriate workflow:

- **NovelFull - Download**: download a single NovelFull book.
- **FreeWebNovel - Download**: download a single FreeWebNovel book.
- **Library - Bulk Download**: the **only bulk workflow**, supporting both sites. Select All, NovelFull or FreeWebNovel; enter saved novel names or source URLs. Up to 10 distinct titles per submission.
- **Covers - Download**: download **images only**, not chapter text.

For novel downloads, provide a source URL (or saved titles for bulk), optionally choose a chapter range and use **Force** only to intentionally redownload. Successful downloads are validated before publication; the completed GitHub Actions artefacts usually expire after **seven days**.

[Detailed downloading and GitHub Actions guide](docs/DOWNLOAD_GUIDE.md)

## Run locally

Requires **Python 3.12**. From the repository root:

~~~powershell
python -m pip install -r requirements.lock
python -m unittest discover -s tests -v
python -u novel_downloader.py --self-test --chapter-range 1-2
~~~

The self-test uses synthetic chapters, without requesting real novels. For an authorised, FanFicFare-supported source:

~~~powershell
python -u novel_downloader.py "https://novelfull.com/your-novel.html" --confirm-rights
~~~

Use a real supported book URL in place of the illustrative URL. For verified full-book completeness, the GitHub Actions workflows are preferable to a direct download without a known chapter count.

## Download the verified Scribble Hub cross-post

For the author's *The Adventurous Gamer Ninja - Daichi Hekima* (series `445037`), there is an internet-based **FicHub + FanFiction.net author-cross-post** route; no pre-existing EPUB is needed:

~~~powershell
python -m tools.verified_crosspost_download "https://www.scribblehub.com/series/445037/the-adventurous-gamer-ninja--daichi-hekima/" --confirm-rights
~~~

Run from the Novel_Library root after installing `requirements.lock`. The CLI validates the author's cross-post, the full story count, EPUB structure and ZIP checksums, then saves a ZIP in `Downloaded_Novels/`. **Other Scribble Hub IDs are rejected unless a verified same-author cross-post is registered.** The tool does not query Scribble Hub directly or circumvent its HTTP 403. [How it works](docs/WEBSITE_SUPPORT.md#scribble-hub).

## Get completed novels onto Windows

Install [GitHub CLI](https://cli.github.com/), then double-click **[Download-All-Novels.cmd](Download-All-Novels.cmd)**. It downloads *existing* complete GitHub Actions artefacts and saves **one validated ZIP per novel** to `Downloaded_Novels/`. It does not download fresh chapters from websites; valid local ZIPs are skipped.

For offline startup validation:

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\download_all_artifacts.ps1 -CheckSetup
~~~

[Windows setup, ZIP validation, legacy repacking and troubleshooting](docs/DOWNLOAD_GUIDE.md#windows-download-completed-novels)

## Import existing books and maintain metadata

- **PDF to novel ZIP:** put authorised, selectable-text PDFs in `PDF-to-Novel/PDFs/` and run [Convert-PDFs.cmd](PDF-to-Novel/Convert-PDFs.cmd). See [PDF converter instructions](docs/PDF_TO_NOVEL.md).
- **Local EPUB to novel ZIP:** use `python -m tools.import_local_epub` for an authorised EPUB from Royal Road, WTR-Lab or Scribble Hub. See [website/import capabilities](docs/WEBSITE_SUPPORT.md#scribble-hub).
- **Covers and synopsis repairs:** see [metadata and archive maintenance](docs/METADATA_GUIDE.md).

A complete book normally contains `source.epub`, `metadata.json`, `chapters.json`, `chapter_*.txt` and an optional cover. [DOWNLOADED_NOVELS.md](DOWNLOADED_NOVELS.md) lists completed historical downloads, but its links are **not permanent storage**.

## Documentation

| Guide | Contents |
| --- | --- |
| [Supported websites](docs/WEBSITE_SUPPORT.md) | All sources, download status, URL formats, experimental limitations and offline imports |
| [Download and Windows guide](docs/DOWNLOAD_GUIDE.md) | NovelFull, unified bulk, chapter batching, artefacts, registry and Windows retrieval |
| [Metadata and archive guide](docs/METADATA_GUIDE.md) | Covers, EPUB descriptions, synopsis repair and archive safety |
| [PDF conversion](docs/PDF_TO_NOVEL.md) | PDF chapter detection, validation and manual corrections |
| [Source feasibility research](docs/experimental-sources.md) | Royal Road, WTR-Lab, Novel Fire and Light Novel Pub investigations |
| [AI agent technical handbook](AGENTS.md) | Full architecture, file contracts, implementation and development invariants |

**Only download and archive material you have permission to store.** The project does not bypass source-site restrictions. Never commit novel text, EPUBs, personal files or secrets. GitHub Actions artefacts from a public repository may be accessible to other users.
