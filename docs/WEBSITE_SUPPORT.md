# Website support and download capabilities

> **Maintained against the Novel_Library implementation, 14 November 2026.** This page describes **which sources this repository can download from**, versus which it can only investigate or import from pre-existing files. Website access and authorisation can change; the presence of code is not a guarantee that a particular live novel downloads successfully.

Back to the [README](../README.md) · [Detailed download guide](DOWNLOAD_GUIDE.md) · [Experimental source research](experimental-sources.md)

## At a glance

| Website | Full website download available? | Supported operation | Where |
| --- | --- | --- | --- |
| **NovelFull** (`novelfull.com`) | **Yes** | FanFicFare-powered single or bulk chapter-range downloads; verified whole-book EPUB assembly | [NovelFull workflow](../.github/workflows/download-novel.yml), [bulk workflow](../.github/workflows/library-bulk-download.yml) |
| **FreeWebNovel** (`freewebnovel.com`) | **Yes**, accessible public chapters only | Dedicated sequential downloader; validated range assembly, single or bulk | [FreeWebNovel workflow](../.github/workflows/freewebnovel-download.yml), [bulk workflow](../.github/workflows/library-bulk-download.yml) |
| **Scribble Hub** (`scribblehub.com`) | **No general live Scribble Hub downloader** | One verified same-author FanFiction.net cross-post via FicHub (series 445037); authorised offline EPUB import; direct Scribble Hub HTTP 403 | [Cross-post details](#scribble-hub) |
| **WebNovel** (`webnovel.com`) | **No** | Book metadata probe, at most two public test chapters where accessible; offline saved-HTML/TXT/JSON imports | [WebNovel probes and import tools](#webnovel) |
| **Royal Road** (`royalroad.com`) | **No enabled website-download workflow** | Convert an already-authorised local EPUB; offline saved-page feasibility | [Local EPUB importer](../tools/import_local_epub.py) |
| **WTR-Lab** (`wtr-lab.com`) | **No** | Convert an already-authorised local EPUB; offline saved-page feasibility | [Local EPUB importer](../tools/import_local_epub.py) |
| **Novel Fire** (`novelfire.net`) | **No** | Offline analysis of saved HTML (book, index and up to two chapters) | [Feasibility tool](../tools/source_feasibility.py) |
| **Light Novel Pub** (`lightnovelpub.com`) | **No** | Offline analysis of saved HTML where suitable | [Feasibility tool](../tools/source_feasibility.py) |

**Meaning of “Yes”:** an actual chapter-fetching and complete-book assembly workflow exists in this repository. It does **not** mean all titles are currently reachable, have consecutive readable chapters, or are authorised for archiving. In particular, FreeWebNovel's original public two-chapter test was verified on 10 November 2026; a complete live full-book run was **not established by that test**.

**FanFicFare note:** its dependency contains additional site adapters, including Royal Road, but this project's existing hosted download workflows have only been configured and tested for the two full-download websites above. Do not label every FanFicFare adapter a supported website in the project's Actions menus.

## Full-download websites

### NovelFull

- **Website:** https://novelfull.com/
- **Typical book URL:** `https://novelfull.com/<title-slug>.html`
- **Single-book Action:** **NovelFull - Download**
- **Bulk Action:** **Library - Bulk Download** (website = NovelFull or All)
- **Direct CLI:** `python -u novel_downloader.py "<authorised-https-book-url>" --confirm-rights`
- **Implementation:** [`novel_downloader.py`](../novel_downloader.py), [`fff_progress_runner.py`](../fff_progress_runner.py), [`tools/chunked_download.py`](../tools/chunked_download.py).

FanFicFare supplies a supported-site book reader. The Actions pipeline discovers the chapter count, splits the selected inclusive range into normally **200-chapter batches**, and adapts concurrency up to six workers. Only complete, source-matched pieces with all expected positions and valid chapter hashes may be reused or assembled. The final EPUB is checked against the TXT chapter collection.

Each successful novel produces a temporary GitHub Actions artefact and a **metadata-only** registry update in [`downloaded_novels.json`](../downloaded_novels.json). Downloaded content does not become a Git-tracked file. The source EPUB may also supply a synopsis, genre, status and cover; genuinely absent metadata is left absent.

**Caveat:** the direct CLI cannot prove a whole book is complete without an authoritative expected chapter count (use `--expected-chapters` or the bounded Actions workflow). FanFicFare's site adapters depend on the remote site's current layout. The workflow can fail cleanly if a source changes.

### FreeWebNovel

- **Website:** https://freewebnovel.com/
- **Typical book URL:** `https://freewebnovel.com/novel/<title-slug>`
- **Single-book Action:** **FreeWebNovel - Download**
- **Bulk Action:** **Library - Bulk Download** (website = FreeWebNovel or All)
- **Direct CLI:** `python -m tools.freewebnovel_downloader "<authorised-https-book-url>" --chapter-range 1-2 --confirm-rights`
- **Implementation:** [`tools/freewebnovel_downloader.py`](../tools/freewebnovel_downloader.py) and [`tools/freewebnovel_chunks.py`](../tools/freewebnovel_chunks.py).

**This is not a FanFicFare adapter.** The independent downloader reads only publicly available book and chapter pages. A standalone call accepts **at most 100 consecutive chapters**, while its Actions workflow normally uses **50-chapter batches** and at most **two simultaneous batches** per book. Requests inside each batch are sequential, with a one-second delay.

Every chapter must be readable and correctly numbered; unexpectedly empty/short text, site-access challenges, locked pages, missing chapters and repeated chapter bodies are rejected rather than silently omitted. Output uses the shared `source.epub`, TXT chapters, manifest, metadata and optional cover conventions. Validated complete batches can be reused while artefacts are available.

**Verification caveat:** an initial live two-chapter test against *The First Order* was reported successful on 10 November 2026, but that does not establish full-book availability for the site as a whole. Site access changes or non-consecutive chapter numbering can prevent a complete download. No login, paywall, CAPTCHA or anti-bot workaround is supported.

### Single or multiple novels

Use **[Library - Bulk Download](../.github/workflows/library-bulk-download.yml)** to choose All, NovelFull or FreeWebNovel and enter either saved novel names or source URLs. It supports up to **10 distinct novels** in a submission, with at most three NovelFull and two FreeWebNovel books running concurrently. Unknown/ambiguous saved names and unsupported URL/site mismatches fail before downloading.

This is deliberately the **only** combined bulk menu. A completed artefact recorded in the download registry is skipped unless Force is selected; previously validated chapter batches can also be reused. Details: [download guide](DOWNLOAD_GUIDE.md).

## Websites without full-download support

### Scribble Hub

- **Website:** https://www.scribblehub.com/
- **Typical URL:** `https://www.scribblehub.com/series/<numeric-id>/<story-slug>/`
- **Direct Scribble Hub status as tested on 14 November 2026:** **not a supported automated Scribble Hub website downloader**. Separately, one exact title is now supported via its author's verified **FanFiction.net cross-post** and the documented FicHub EPUB export API, without contacting Scribble Hub. Authorised offline EPUB imports also remain available.
- **Existing dependency support:** `fanficfare==4.63.0` includes `adapter_scribblehubcom.py`, which recognises Scribble Hub series URLs, discovers metadata and chapters through the site adapter, and extracts chapter pages when accessible. The adapter performs a POST to `/wp-admin/admin-ajax.php` during chapter-index discovery.
- **Live test:** [GitHub Actions run #43567663190](https://github.com/RichardDaffern/Novel_Library/actions/runs/43567663190), isolated branch `test/scribblehub-metadata-20261114`. The installed adapter **recognised** `https://www.scribblehub.com/series/2677327/blueflame-the-starless-king/`, but FanFicFare's metadata-only CLI returned an **HTTP 403 Forbidden** error. The diagnostic deliberately suppresses raw page contents, so this test does **not** isolate whether the 403 arose on the series-page request or the chapter-index AJAX request.
- **Initial live test boundaries:** no story chapters were requested or saved, no EPUB or ZIP was generated, no proxies/login/challenge handling were used, and no production downloader, bulk menu or registry was altered. The diagnostic step was intentionally `continue-on-error`, so a green overall Actions run must **not** be mistaken for successful Scribble Hub discovery.
- **External evidence:** upstream FanFicFare [issue #1353](https://github.com/JimmXinu/FanFicFare/issues/1353) reported a 403 on the AJAX endpoint in June 2026; [issue #1397](https://github.com/JimmXinu/FanFicFare/issues/1397) recorded an access-challenge/HTML mismatch, with a later September 2026 report of intermittent recovery. Current site access can vary.
- **Legal/permissions:** Scribble Hub's [Terms of Service](https://www.scribblehub.com/terms-of-service/) do not grant blanket permission to archive other authors' chapters. Reading a public series page does not establish permission to download and distribute its novel.
- **Further tests, 14 November 2026:** [diagnostic run #43569079591](https://github.com/RichardDaffern/Novel_Library/actions/runs/43569079591) made a single standard request for the site's `robots.txt` and received **HTTP 403**. It then **stopped** without requesting a series page, RSS feed, chapter index or chapter content. A failed robots request does not establish the site's actual robots rules; it does confirm this runner could not retrieve those rules.
- **Offline adapter checks:** six original-synthetic regression tests cover source URL recognition, site exclusion from the active bulk planner, metadata and AJAX-TOC parsing, chapter selector, error-page rejection and two-chapter EPUB/TXT/manifest construction. After correcting an independent Windows LF/CRLF file-hash bug in [PR #132](https://github.com/RichardDaffern/Novel_Library/pull/132), the isolated Linux and Windows test run [#43569472284](https://github.com/RichardDaffern/Novel_Library/actions/runs/43569472284) passed. These are **offline** fixtures and **not** evidence of successful remote chapter downloads.
- **RSS:** Scribble Hub has publicly documented RSS feeds, but they were **not** tested live from the runner after robots access was refused. RSS notifications do not by themselves prove the completeness of a novel's chapter table of contents.
- **Authorised local EPUB import (no website requests):** if you already possess a legitimately obtained EPUB, convert it with:

~~~powershell
python -m tools.import_local_epub --epub "My Authorised Book.epub" --source-url "https://www.scribblehub.com/series/2677327/blueflame-the-starless-king/" --confirm-rights
~~~

  This example URL is provenance metadata only. The command never downloads this book. It validates the EPUB's chapters, SHA-256 checksums and optional cover, and publishes a single ZIP. ZIP identity uses Scribble Hub's numeric series ID, so a changed title slug cannot silently create a duplicate novel. Existing ZIPs are preserved unless `--replace` is supplied. The provided EPUB must be authorised and complete: the converter verifies its internal consistency but cannot independently prove Scribble Hub's live chapter count.
- **Internet retrieval of one verified author cross-post:** the author **MonkWithAPen** also publishes *The Adventurous Gamer Ninja - Daichi Hekima* as FanFiction.net story **14031894**. On 14 November 2026, FicHub's API returned the correct author, title, story ID and **432 chapters**. A read-only verification fetched the resulting EPUB: it had **434 readable sections**, comprising the two expected preliminary sections followed by the **432 story chapters**. The first story chapter was *My Second Chance* and the 432nd was *Orochimaru's Contingency*. The original export was only inspected on a temporary runner and never uploaded publicly.
- **Verified internet-download command (no EPUB input):**

~~~powershell
python -m tools.verified_crosspost_download "https://www.scribblehub.com/series/445037/the-adventurous-gamer-ninja--daichi-hekima/" --confirm-rights
~~~

  It calls only `https://fichub.net/api/v0/epub` and a validated FicHub EPUB cache URL. It does **not** fetch pages from Scribble Hub or FanFiction.net itself. It rejects unknown Scribble Hub IDs, mismatched source identity, author/title or count, unsafe returned EPUB URLs, unexpected front matter, missing checkpoint chapters and failed ZIP hashes. It never automatically retries HTTP 429 or publishes an incomplete ZIP. The ZIP goes to `Downloaded_Novels/` and can be deliberately refreshed with `--replace`. The separate, regular bulk GitHub Actions workflow is unchanged.
- **Scope:** this is a **specific author-verified cross-post**, not general Scribble Hub coverage. A FicHub cache may be temporarily unavailable or stale, and FicHub's API is explicitly unstable; a valid EPUB can only be claimed once the generated archive actually passes the full downloader's checks. Other Scribble Hub works require their own verifiable author cross-post and explicit registration in [verified_crossposts.json](../tools/verified_crossposts.json), or an EPUB you independently hold with permission.
- **Decision:** retain direct Scribble Hub **website downloading** as feasibility only. Do **not** add it to the unified bulk website dropdown, launch chapter downloads, or create a production workflow on the strength of an adapter being present. A future implementation needs verified permitted access, reliable metadata and chapter discovery, two authorised chapter fixtures, and all normal archive-integrity tests. If the site refuses automated access, stop instead of attempting to evade protections.

For development background see [experimental source research](experimental-sources.md#scribble-hub-feasibility).

### Royal Road and WTR-Lab

For an EPUB you already hold **with authorisation**, this repository provides an offline converter:

~~~powershell
python -m tools.import_local_epub --epub "My Authorised Novel.epub" --source-url "https://royalroad.com/fiction/21220/mother-of-learning" --confirm-rights
~~~

The URL is illustrative identity metadata; the command does **not** download that book or grant permission to archive it. It reads the local EPUB, checks ZIP safety/CRC, exports chapters, creates a new `novel-<stable-url-hash>.zip` and refuses overwrite unless `--replace` is explicitly requested.

**Royal Road:** FanFicFare has an adapter and the site's author export supports some EPUB use cases, but this project's GitHub workflows do **not** offer a dedicated Royal Road source. Chapter IDs are not reading-order positions. Respect each work's permissions.

**WTR-Lab:** no automated downloader is enabled. Its published rules restrict automated requests and copying, and some chapters are locked. Offline import is possible for a user-supplied, authorised EPUB only, not for automatically collected site text.

For source-policy detail, examples and offline page analysis, see [experimental-sources.md](experimental-sources.md).

### Novel Fire and Light Novel Pub

These sites have **offline feasibility analysis only**. [`tools/source_feasibility.py`](../tools/source_feasibility.py) can parse book information, saved chapter-index HTML and up to two saved chapters; it performs no website requests and does not produce a complete EPUB.

- **Novel Fire** (`novelfire.net`): catalogue routes have been studied, but published terms prohibit scraping/crawling without relevant permission. No chapter-download workflow exists.
- **Light Novel Pub** (`lightnovelpub.com`): older indexed book pages can be analysed offline, but current technical access and download permissions are unverified. No chapter-download workflow exists.
- **Light Novel World / `lightnovelpub.org`** is not equivalent to `lightnovelpub.com`; the older site has been reported shut down. It is not supported here.

The detailed feasibility research, format observations and acceptance requirements are in [experimental-sources.md](experimental-sources.md).

### WebNovel

**WebNovel is not a full-book website-download source in this repository.** Its public book metadata pages may expose titles, authors and chapter counts, but this does not permit automated chapter archiving. Paid/locked chapters, login sessions and access-control bypasses are outside the supported scope.

Available **separate, constrained tools**:

| Tool | Purpose | Limitation |
| --- | --- | --- |
| [`tools/webnovel_probe.py`](../tools/webnovel_probe.py) | Inspect public book metadata | No chapter downloads; returns `chapter_export_verified: false` |
| [`tools/webnovel_http_diagnostics.py`](../tools/webnovel_http_diagnostics.py) | Inspect public-page HTTP status | No persisted chapter text |
| [`tools/webnovel_browser_probe.py`](../tools/webnovel_browser_probe.py) | Ordinary browser feasibility | At most two public chapter pages; no challenge bypass |
| [`tools/webnovel_public_two_chapter.py`](../tools/webnovel_public_two_chapter.py) | Limited public chapter export when permitted | One book page plus at most two readable chapter pages |
| [`tools/webnovel_saved_pages.py`](../tools/webnovel_saved_pages.py) | Offline import of user-saved HTML/TXT chapters | One or two chapters |
| [`tools/webnovel_export.py`](../tools/webnovel_export.py) | Offline import of user-supplied JSON chapter text | At most two chapters |
| [`tools/webnovel_bulk_import.py`](../tools/webnovel_bulk_import.py) | Offline import of consecutive saved local HTML/TXT chapters | At most 10,000; **not** a website scraper |

For example, the metadata-only probe is:

~~~powershell
python -m tools.webnovel_probe "https://www.webnovel.com/book/22196546206090805"
~~~

It does not download chapter bodies, and ordinary scripted requests have previously encountered site challenges. Offline saved-page imports require user-held files and permission; they never bypass an access restriction.

See [WebNovel browser probe](../tools/WEBNOVEL_BROWSER_PROBE.md), [saved-page import](../tools/WEBNOVEL_SAVED_PAGE_IMPORT.md), [bulk local import](../tools/WEBNOVEL_BULK_IMPORT.md), [two-chapter public probe](../tools/WEBNOVEL_PUBLIC_TWO_CHAPTER.md), and [JSON import](../tools/WEBNOVEL_EXPORT.md).

## Outputs, rights and changes to site support

Supported completed-book outputs contain `metadata.json`, `chapters.json`, `source.epub`, numbered UTF-8 `chapter_*.txt` and an optional cover, generally packaged as a single-book ZIP after local Windows retrieval. The [download guide](DOWNLOAD_GUIDE.md) explains transient GitHub Actions artefacts, source URL identity and data-integrity checks.

To add another **live** website, first verify archiving permission, stable public chapter access, complete catalogue ordering, fail-closed extraction and offline regression coverage. Keep the existing NovelFull and FreeWebNovel paths functioning, and extend the **single** bulk menu rather than creating another competing bulk action.

**Download and store only material you have the right to archive.** Neither this project nor the presence of a site adapter authorises redistribution of novels, evasion of site protections or archiving of premium/locked content.
