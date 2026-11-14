# Novel_Library: Deep Technical Handbook for AI Agents and Contributors

> **Purpose:** A detailed, repository-specific orientation for an AI coding agent, developer, maintainer or auditor who needs to work safely and effectively on Novel_Library.
>
> **Scope:** Only the `RichardDaffern/Novel_Library` repository. This is a **download, acquisition, conversion, validation, packaging, metadata and local retrieval** project, **not** the web reader or the Hugging Face dataset controller.
>
> **Source baseline:** Reviewed against `main` at commit `24c2f1414a6a3d4ea9c76f31e8e74da728814053` (13 November 2026). This is a descriptive snapshot, **not a substitute for checking the latest code**.
>
> **Precedence:** For actual behaviour, trust executable code and the current tests first; then inspect workflow YAML, the README and focused documentation. If a statement here conflicts with the repository, verify and update this file in the same change. Never silently assume a feature described as experimental is production-ready.

## 1. Mission, boundaries and design philosophy

Novel_Library is a Python-centric, local-first toolkit for converting content a user is authorised to archive into consistent, inspectable novel artefacts. Its core output is an EPUB, UTF-8 text chapters and JSON metadata. It also supplies GitHub Actions workflows for fetching or assembling permitted chapter ranges, a metadata-only index of completed downloads, a Windows tool for retrieving completed GitHub Actions artefacts, and local PDF/EPUB import utilities.

The project exists because long novels are frequently delivered as thousands of independently numbered chapters. A one-job scraper or one giant EPUB conversion can time out, lose progress, collide with another novel's files, or silently omit chapters. This repository favours bounded work, verifiable identities, recoverable checkpoints, strict manifests and explicit failures over optimistic “best effort” archives.

### What is in scope

- Acquire authorised books from **NovelFull** using the established **FanFicFare** integration and its site adapter.
- Acquire authorised, publicly readable **FreeWebNovel** chapter ranges through a separate, deliberately conservative downloader.
- Split large books into independent, bounded batches; reuse only validated complete batches; assemble one verified EPUB and its chapter TXT collection.
- Export directly imported EPUBs, package authorised local EPUBs, convert locally supplied selectable-text PDFs, extract optional covers and preserve sourced metadata.
- Track completed GitHub Actions artefacts in a readable metadata-only registry.
- Download **already generated** GitHub Actions artefacts to Windows and package each complete novel as its own verified ZIP.
- Perform isolated source-feasibility experiments without enabling unapproved websites or bypassing access controls.
- Run offline unit and synthetic end-to-end regression checks on Linux and Windows.

### Explicit non-goals

- This repository is **not a hosted reader**, not the user's personal library web application, and not the private dataset administrator.
- It does **not** own the external application's user accounts, cloud synchronisation, ratings, reading progress or hosted collection metadata.
- It does **not** persist full novel text in Git history or in `downloaded_novels.json`. A GitHub Actions artefact is temporary delivery storage, not permanent backup storage.
- It does not grant permission to scrape, copy, redistribute, unlock, or circumvent restrictions on any third-party site. A `--confirm-rights` flag is a user declaration, not a legal or technical bypass.
- It must never implement CAPTCHA-solving, account-cookie harvesting, paywall bypass, hidden API scraping, challenge evasion or premium-content unlocking.
- A live website returning HTTP 200 does not prove completeness, licence, or compatibility.

### Architectural principles

1. **Source identity is stronger than a title.** Titles and final URL path components can collide.
2. **Correctness before publication.** Do not label a novel complete until expected chapter positions and files are validated.
3. **Non-destructive by default.** Existing ZIPs or complete books must not be overwritten through ordinary retries.
4. **Checkpoints are not completions.** Keep recoverable partial work separate from published completed artefacts.
5. **Reproducible, offline-first CI.** Synthetic fixtures and deterministic installs must remain the required checks; any live metadata smoke is supplementary.
6. **Site adapters remain isolated.** Changes to experimental sites must not regress NovelFull, FreeWebNovel, existing manifests, or Windows packaging.
7. **Respect operator boundaries.** Destructive data operations, external downloads, API credentials and publication are separate actions requiring the correct permissions and safeguards.
8. **Never invent book metadata.** Missing synopsis, cover, genre or publication status should be absent or explicitly reported, not guessed.

## 2. One-minute architectural map

Conceptual data flow:

~~~text
Authorised source book / user-supplied EPUB / user-supplied PDF
               |
               +--> NovelFull via FanFicFare + fff_progress_runner.py
               |       |
               |       +--> individual verified chapter-range jobs
               |       +--> cached complete range reuse (when available)
               |
               +--> FreeWebNovel conservative public-page downloader
               |       |
               |       +--> numbered, verified 50-chapter workflow jobs
               |
               +--> offline import_local_epub.py / pdf_to_novel.py
                       |
                       v
        source.epub + chapter_*.txt + metadata.json
                       + chapters.json + optional cover
                       |
          source identity + count + order + SHA-256 checks
                       |
           +-----------+--------------------+
           |                                |
   GitHub Actions completion        Local ZIP conversion
           |                                |
   Temporary final artefact          One-book verified ZIP
           |                                |
   Metadata-only registry PR        Private downstream import,
           |                        if explicitly performed outside
   downloaded_novels.json           this repository
           + DOWNLOADED_NOVELS.md
           |
   Download-All-Novels.cmd
   (fetch existing complete artefacts; validate; save local ZIPs)
~~~

The acquisition tools and the downstream reading/storage repositories communicate through **files and contracts**, not through a shared runtime library. A successful ZIP generation here is **not** evidence that a separately maintained hosted importer has accepted the package.

## 3. Repository tree and ownership

This section is a navigation map, not an exhaustive list of every test.

| Path | Responsibility | Change caution |
| --- | --- | --- |
| `README.md` | Main user guide and up-to-date operational instructions | Update when behaviour or commands change |
| `AGENTS.md` | This detailed agent/contributor reference | Keep aligned with executable source |
| `novel_downloader.py` | Main FanFicFare-backed direct downloader; EPUB spine parsing, chapters, staging and identity safety | High: common library functions used by several tools |
| `fff_progress_runner.py` | FanFicFare callback wrapper for chapter progress and temporary chapter checkpoints | High: partial-download resilience |
| `tools/chunked_download.py` | NovelFull range planning, caching, batch validation, EPUB assembly | High: completeness, ordering, metadata and artifact reuse |
| `tools/freewebnovel_downloader.py` | Separate public-page sequential FreeWebNovel range downloader | High: site restrictions and fail-closed parser |
| `tools/freewebnovel_chunks.py` | FreeWebNovel workflow orchestration using shared batch APIs | High: keep independent from NovelFull |
| `tools/download_registry.py` | Canonical URLs, ranges, availability, registry records and Markdown rendering | High: previously downloaded book selection |
| `tools/publish_registry.py` | Retryable optimistic registry PR publishing on the latest `main` | High: concurrent download completion |
| `tools/library_bulk.py` | Single consolidated bulk workflow planning by names or URLs, grouped by site | High: avoid incorrect title-to-URL guessing |
| `tools/bulk_download.py` | General local/multiple-URL planning and execution utilities | Maintain tests even if a newer workflow path is preferred |
| `tools/epub_source_metadata.py` | Recover source EPUB description, genres and publication status from OPF | Preserve data instead of deriving it from novel prose |
| `tools/novel_covers.py` | Image detection, public URL restrictions, image limits, EPUB cover extraction | Covers are optional and untrusted image input |
| `tools/download_covers.py` | Cover-only collection from existing registry Markdown | Never download/rewrite chapter text |
| `tools/repair_synopsis.py` | Dry-run-first, validated repair of existing novel ZIP descriptions | Protect original ZIP on failure |
| `tools/pdf_to_novel.py` | Offline selectable-text PDF inspection, extraction, EPUB/ZIP creation and verification | High: chapter boundaries and source-text preservation |
| `tools/pdf_batch.py` | Convert every local PDF, skip good existing ZIPs, produce review plans when needed | High: never destroy input PDFs |
| `tools/import_local_epub.py` | Offline, source-identified ZIP packaging of already-authorised EPUB files | High: validation budgets and overwrite rules |
| `tools/download_all_artifacts.ps1` | Fetch existing GitHub Actions artefacts to Windows, handle authentication/logging/repacking | High: PowerShell 5.1 and local safety |
| `tools/zip_novel_artifacts.ps1` | Validate each book folder and produce reader-compatible, one-book ZIPs | High: ZIP format and duplicate detection |
| `Download-All-Novels.cmd` | Windows entry point for existing artefact retrieval | Preserve argument forwarding and visible errors |
| `PDF-to-Novel/Convert-PDFs.cmd` | Windows entry point for batch PDF conversion | Preserve relative paths, confirmation and pause |
| `PDF-to-Novel/PDFs/` | Local PDF inputs; gitignored | Do not commit books |
| `PDF-to-Novel/Novels/` | Local converted ZIPs and reports; gitignored | Do not commit books |
| `docs/PDF_TO_NOVEL.md` | PDF structure, manual review, limitations | Read before changing PDF heuristics |
| `docs/experimental-sources.md` | Source permissions and research decisions | Read before introducing new sites |
| `tools/WEBNOVEL_*.md` | WebNovel feasibility and locally saved import instructions | Do not mistake prototypes for production scrapers |
| `tools/FREEWEBNOVEL_FEASIBILITY.md` | Early two-chapter public compatibility notes | The working full-range implementation lives elsewhere |
| `downloaded_novels.json` | Metadata-only history of completed downloads and artefact links | Do not hand-edit concurrent updates without care |
| `DOWNLOADED_NOVELS.md` | Generated human-readable registry index | Maintain synchronisation with JSON |
| `novel_sources.json` | Small curated URL/title list for bulk name resolution | Not the downloaded content corpus |
| `requirements.txt`, `requirements-pdf.txt` | Broad developer compatibility constraints | Update deliberately, not incidentally |
| `requirements.lock`, `requirements-pdf.lock` | Resolved Python 3.12 package versions used in CI | Install from these in routine CI/workflows |
| `tests/` | Main offline unit tests, Windows packaging smoke, regressions | Extend alongside production changes |
| `tests_pdf/` | Isolated offline PDF and Windows CMD regression tests | Keep both Windows and Ubuntu passing |
| `.github/workflows/` | Six Actions workflows listed below | Check permissions, source restrictions and artifact retention |

Do not infer that a `tools/` file is automatically part of the regular production flow. Several modules are intentionally isolated feasibility stages.

## 4. Environment and first-day setup

### Supported practical environment

- The active workflows use **Python 3.12**. Do not assume that changing the tested Python version is harmless.
- The code is Python-first. EPUB extraction uses ZIP/XML and Beautiful Soup; FanFicFare performs supported-site acquisition. Pillow handles cover images. PDF conversion uses PyMuPDF (`fitz`) and Pillow.
- The normal downloader and PDF converter use separate lockfiles. The PDF package set is deliberately optional for normal novel downloads.
- Linux Ubuntu runners run primary tests and downloads; Windows runners test PowerShell, CMD launchers, novel ZIPs and offline PDFs.
- `gh` is used for querying/downloading GitHub Actions artefacts and registry PR publication. The user's local laptop only needs it for relevant workflows.
- Windows PowerShell **5.1** is a supported target for the one-click archive downloader; do not assume PowerShell 7-only syntax.

From the project root, a conservative normal setup is:

~~~powershell
python -m pip install -r requirements.lock
python -m pip check
python -m unittest discover -s tests -v
~~~

For PDF work:

~~~powershell
python -m pip install -r requirements-pdf.lock
python -m unittest discover -s tests_pdf -p "test_pdf_*.py" -v
~~~

Test the FanFicFare downloader without a live network request:

~~~powershell
python -u novel_downloader.py --self-test --chapter-range 3-4 --output-dir smoke
~~~

Do not run the two-chapter self-test as evidence that a real NovelFull page or a user's full novel still downloads. Distinguish **synthetic correctness** from **site availability**.

### Developer dependency policy

- `requirements.txt` contains compatible ranges for FanFicFare, Beautiful Soup and Pillow.
- `requirements-pdf.txt` defines the separate PDF requirements.
- `requirements.lock` and `requirements-pdf.lock` pin resolved versions, including transitive dependencies, for Python 3.12.
- The current lockfiles are **version locks, not hash-pinned wheel locks**.
- If upgrading, regenerate the affected lockfile with a reviewed resolver, check the actual installed version graph, and run both relevant operating systems in CI.
- Never casually replace locked installation in CI with an unconstrained `pip install -U`.

## 5. Data contracts: book directory, EPUB, chapters and ZIP

This section is especially important. There are **multiple producers** and at least two packaging pathways, so do not impose one producer's incidental filename style on all the others.

### Standard book directory

A completed book commonly looks like:

~~~text
some-book-folder/
    metadata.json
    chapters.json
    source.epub
    chapter_00001.txt
    chapter_00002.txt
    ...
    cover.jpg                # optional; cover.png also allowed
~~~

Some direct imports use `chapter_0001.txt` instead of five digits, a prologue name, or a `_part02` suffix if printed chapter numbers repeat. The PDF converter uses `chapter_0001.txt`, `chapter_0002.txt` etc. The final batch assembler uses five-digit **position-based** filenames.

**Therefore:** the true set and order of chapters comes from `chapters.json`, not a guessed glob, lexical sorting, or one hard-coded chapter-name width.

### Common metadata shape

`metadata.json` is source- and producer-dependent; common fields include:

~~~json
{
  "title": "Example Novel",
  "author": "Example Author",
  "language": "en",
  "source_url": "https://example.org/example-novel",
  "chapter_count": 2,
  "created_at_utc": "2026-11-13T00:00:00+00:00",
  "format": "epub",
  "chapter_files": "UTF-8 TXT",
  "description": "Source-provided summary when available.",
  "synopsis": "Source-provided summary when available.",
  "genres": ["Example genre"],
  "status": "Completed",
  "cover_image": "cover.jpg"
}
~~~

The sample is **illustrative, not a required universal schema**. `description`, `synopsis`, `genres`, `status` and `cover_image` are optional and must not be fabricated. Other producer-specific fields include `synopsis_pipeline_version`, `cover_pipeline_version`, `assembled_from_batches`, `original_format`, `source_pdf_sha256` and `source_pdf_pages`.

The identity field is `source_url`, not an arbitrary display title. For local PDF conversion the identity is `pdf://sha256/<full-pdf-sha256>` instead of a public website URL.

### Chapter manifest

A representative `chapters.json` row:

~~~json
{
  "position": 1,
  "chapter_number": 1,
  "title": "Chapter 1",
  "file": "chapter_00001.txt",
  "word_count": 1234,
  "sha256": "64-lowercase-hex-characters-calculated-from-the-TXT-bytes"
}
~~~

The digest shown is explanatory text, **not a valid hash fixture**. In real output the digest is computed from the UTF-8 chapter content. The chapter TXT typically contains the chapter title, a blank line and the body. Test exact bytes, encoding and line-endings where hashes are involved.

- **`position`:** the one-based position in the downloaded/assembled selection; it is not necessarily the chapter number printed in the title.
- **`chapter_number`:** parsed or assigned chapter number, which may differ from position, especially with prologues or unusual titles.
- **`file`:** the actual basename of that chapter's TXT; use it as the locator.
- **`word_count`:** the word-count contract of the relevant producer. Do not change tokenisation without changing validation and tests.
- **`sha256`:** digest of the generated TXT representation, not just the body. Windows CRLF conversion must be considered before claiming a checksum mismatch.

A valid batch covers **every expected position exactly once, in order**. Reject missing, duplicated, reordered, wrong-source, missing-file, corrupt or unexpected chapter ranges.

### EPUB details

The `source.epub` file is not merely a placeholder. It contains ordered XHTML chapters and OPF metadata. In assembled books, the merger rebuilds EPUB spine/toc and checks that the EPUB can be parsed back into the expected number of chapters. Where available, source OPF descriptions, genre subjects, status and cover information are carried forward.

`novel_downloader.epub_chapters()` reads EPUB spine order. It recognises FanFicFare's chapter markers and has a carefully limited fallback for generic EPUB pages. Cover/TOC pages must not become fake story chapters. It rejects basic unsafe EPUB traversal paths. Do not replace this reader with alphabetical member sorting.

### ZIP formats and ownership

The local Windows ZIP packager and the PDF/local EPUB tools publish **one book per ZIP**, rooted in a single novel directory:

~~~text
novel-some-id.zip
    some-book-folder/
        metadata.json
        chapters.json
        source.epub
        chapter_0001.txt
        chapter_0002.txt
        cover.jpg           # optional
~~~

Not every GitHub Actions artefact is already this final ZIP; workflow artefact storage and portable reader ZIPs are distinct concepts. The Windows downloader fetches the completed Actions artefact, finds the correct book, validates it, and then packages a one-book ZIP.

For local ZIP packaging, **do not identify a novel by ZIP filename alone**. Check its internal metadata `source_url`, expected manifest rows, EPUB presence, and optional cover. The Windows helpers protect existing ZIPs from overwrite, including invalid ones.

An archive that exists on disk is not proof that its chapters are complete or that it belongs to the requested source.

## 6. NovelFull: established acquisition and complete-book assembly

### Direct CLI

`novel_downloader.py` is the public entry point for FanFicFare-supported source URLs.

Examples:

~~~powershell
python -u novel_downloader.py "https://example.org/my-book" --confirm-rights
python -u novel_downloader.py "https://example.org/my-book" --confirm-rights --chapter-range 1-30
python -u novel_downloader.py "https://example.org/my-book" --confirm-rights --expected-chapters 500
python -u novel_downloader.py --import-epub "Authorised Book.epub" --output-dir downloads
~~~

The placeholder URL is only a syntax example. A real network download requires a site actually supported by FanFicFare and permission to archive that content.

Important flags: `--list-only` (FanFicFare metadata discovery), `--chapter-range` / `--range`, `--begin-chapter` / `--end-chapter`, `--output-dir`, `--slug`, `--overwrite`, `--expected-chapters`, `--timeout-minutes` and `--self-test`.

- URL input requires HTTPS and rejects URL credentials, IP literals and certain local/private hostname suffixes. **This is input hardening, not complete DNS-rebinding or redirect-time SSRF protection.** The FanFicFare adapter's own destination handling still matters.
- Download folders use a readable URL-path slug **plus a digest of the source URL**. Two sites with the same path stem must not overwrite each other.
- If a caller supplies the same custom `--slug` for two different URLs, the recorded metadata identity must block cross-book reuse, even when `--overwrite` is supplied.
- An existing EPUB with no verifiable associated source metadata must not be silently claimed as a cache hit.
- A requested exact range or explicit expected chapter count must be checked **before publication**.
- Without an authoritative expected count, a direct unrestricted download warns that completeness cannot be proven. For a verified whole book, favour the GitHub Actions batch workflow.
- Forced redownloads use a temporary sibling directory rather than destroying an already published complete EPUB before success.
- Exported chapter/manifest generations are staged, with a recoverable prior-directory backup and rollback on rename errors. This is **recoverable**, not a magical atomic multi-file transaction under sudden process death.
- Temporary `chapters_in_progress/` checkpoints are removed after successful complete export.

### Progress reporting

`fff_progress_runner.py` observes FanFicFare's chapter completion callback, rather than interpreting every console progress dot as one chapter. It produces chapter counts/progress percentages and writes temporary chapter text checkpoints as individual chapters finish.

Do not delete checkpoints or advertise a partial output as complete after exceptions. Tests in `tests/test_novel_downloader.py` exercise progress and checkpoint behaviour.

### GitHub workflow, step by step

The workflow is `.github/workflows/download-novel.yml`, named **NovelFull - Download**. It can run manually or as a reusable workflow called by the unified bulk job. High-level sequence:

1. **prepare**: read current `main`; validate input; check the JSON registry to skip an already available completed artefact unless `force` is set.
2. **discover**: use FanFicFare metadata-only discovery to establish a positive chapter count; interpret formatted counts carefully (including thousands separators).
3. **plan**: split the requested inclusive range into bounded pieces, by default **200 chapters per piece**, with a cap of **128 pieces**. The planner stores a source-derived identity key, exact bounds and selected work matrix.
4. **chapter-batches**: execute independent jobs for each piece, with bounded concurrency, separate timeouts and recoverable failure artefacts. The planner permits **up to six workers**, according to selected chapter count and available batches.
5. **reuse**: try prior non-expired GitHub Actions artefacts for each exact source/range; validate the cached manifest and SHA-256 values before accepting them.
6. **assemble**: gather the precise completed pieces; reject any missing/duplicated/out-of-order positions; copy verified TXT chapters into the assembled book, rebuild the EPUB, preserve source metadata and verify the new EPUB.
7. **publish artefact**: upload the final completed novel as an Actions artefact, normally retained for **seven days**.
8. **register**: update only the metadata registry through a PR built from the latest `main` (see Section 9).
9. **report**: on failure, explain failed ranges; do not register a partially assembled novel as complete.

The default parallelism is adaptive, not “always six”. Large jobs may run concurrently with **other novels**; duplicate requests for the same URL use workflow concurrency to queue rather than cancel in-progress runs.

### Batch identity and validation

`tools/chunked_download.py` has three CLI actions: `plan`, `fetch` and `assemble`. Key concepts:

- `identity(url)`: a stable digest-based key used in chapter batch artefact names.
- `chapter_plan(url, total, chapter_range, chunk_size)`: exact range, piece boundaries and concurrency matrix.
- `validate_piece(folder, url, key, first, last)`: verifies `part.json` identity, book metadata identity, every selected row position, chapter files/checksums, EPUB presence and cover data when supplied.
- `reuse_complete_piece(...)`: attempts prior Actions artefacts via `gh`; an absent, expired, corrupt, identity-mismatched or old-incompatible cached piece must be fetched again.
- `assemble(...)`: checks complete contiguous coverage and writes one EPUB plus its final chapter TXT/JSON collection.
- `cache_has_synopsis_support(...)`: ensures old NovelFull caches lacking the newer synopsis/cover metadata capabilities are not trusted to preserve those fields.

Some source EPUBs legitimately have no description or cover. The code must retain a warning/absence, **not** invent a synopsis or reject the book solely because its source supplied no cover.

## 7. FreeWebNovel: separate production path with restricted requests

**FreeWebNovel is not a FanFicFare adapter in this project.** Do not send it through `novel_downloader.py` as a substitute for the dedicated implementation.

Components:

- `tools/freewebnovel_probe.py`: constrained catalogue/chapter compatibility probing, at most two chapter requests.
- `tools/freewebnovel_downloader.py`: site-specific book details, sequential numbered chapter extraction, text-quality checks, checkpoint files, optional cover, EPUB creation.
- `tools/freewebnovel_chunks.py`: batch plan/fetch/assemble wrapper.
- `.github/workflows/freewebnovel-download.yml`: dedicated single-book Actions workflow with the same high-level prepare/batches/assemble/register structure.

Operational rules:

- Only validated `https://freewebnovel.com/novel/<slug>`-style public book URLs are accepted.
- The standalone downloader accepts at most **100 consecutive chapters** in one call. The workflow normally divides into **50-chapter** pieces.
- The workflow uses at most **two concurrent chapter-batch jobs per book**. Requests **inside** a batch are sequential, with a one-second delay.
- The public catalogue's highest numbered chapter link is used as an upper bound; it is not a blanket guarantee that each intervening chapter exists or is readable.
- Each requested chapter must be present, correctly numbered, legible, non-locked, substantial enough for extraction, and independently validated.
- The parser rejects challenges, recognised locked content, missing reader selectors, suspiciously short chapter bodies, repeated chapters and numbering inconsistencies instead of silently skipping them.
- Recoverable per-range checkpoints may contain validated rows. Checkpoints themselves never become completed registry entries.
- Covers remain optional; a failed cover lookup must not lead to fabricated or substituted artwork.
- No login, concurrency within one batch, automated challenge retries, paywall workarounds or anti-bot evasion.
- The main README records a locally verified initial two-chapter test from 10 November 2026; **that is not proof that every currently available title supports complete downloading**.

Local example (requires rights and a real, permitted source):

~~~powershell
python -m tools.freewebnovel_downloader "https://freewebnovel.com/novel/the-first-order" --chapter-range 1-2 --output-dir freewebnovel-test --confirm-rights
~~~

This example makes live source requests. **Do not use it in deterministic CI or run it merely to explore a production bug without explicit purpose and permission.**

## 8. One unified bulk workflow, not multiple competing bulk menus

`.github/workflows/library-bulk-download.yml` is named **Library - Bulk Download** and is the single user-facing bulk workflow.

The user chooses **All**, **NovelFull**, **FreeWebNovel** or **Scribble Hub**, and enters one or more saved novel names or exact source URLs. The input may combine names and URLs. A chapter range can optionally apply to the selection, and `force` bypasses an available-artifact skip.

Implementation is in `tools/library_bulk.py`:

- Resolve names from the downloaded registry and `novel_sources.json`.
- Reject unknown or ambiguous names rather than guessing which book is meant.
- Validate each URL's source site, path and the selected website filter.
- No arbitrary ten-novel limit. Respect the GitHub Actions **256-job matrix limit** for scheduled (non-skipped) downloads; fail with an informative message rather than letting GitHub silently reject an oversized matrix.
- Check available completed artefacts and skip them by default.
- Group requested work by site; call existing **NovelFull - Download**, **FreeWebNovel - Download** and the **verified Scribble Hub - Download** reusable workflows. Scribble Hub's `workflow_call` requires explicit `confirm_rights` and only allowlisted same-author cross-posts; only full-book exports are supported.
- Limit simultaneous novels to at most **three NovelFull**, **two FreeWebNovel** and **one Scribble Hub** jobs.
- Preserve each child's own chapter batch limits and per-book validation.
- After **all** children finish, the summary job runs under `if: always()` and retrieves every successful `novel-<run-id>-*` artefact, even when the parent run is red. `tools/bulk_recovery.py` validates source identity, EPUB ZIP CRC, manifest ordering and each TXT SHA-256 before packaging one portable ZIP per complete novel into a seven-day `bulk-successful-novels-<run-id>` recovery artefact, plus a JSON manifest of missing/rejected downloads.
- Never delete independently uploaded successful child artefacts when any other book, registry update or recovery job fails. The overall bulk workflow must still signal failures, without losing verified successes. Recovery has an intentional 1.75 GiB aggregate size safety limit; original child artefacts persist if exceeded.

Do not create another bulk UI just because a source adds a new adapter. Extend the single planner and dispatch model only after that site's legal, technical and testing requirements are met.

Useful read-only command:

~~~powershell
python -m tools.library_bulk list
~~~

`tools/bulk_download.py` is an additional generic planner/running utility. Read it before modifying shared URL/range conventions, but **the endorsed combined Actions menu is Library - Bulk Download**.

## 9. Download registry, caching, artefact expiration and concurrent publication

### Registry sources of truth

- `downloaded_novels.json` has top-level `{"version": 1, "novels": [...]}`.
- Each novel has a canonical source URL, display title, author and a `downloads` history array.
- Each download record stores `range`, `status`, `chapter_count`, `run_id`, `run_url`, `artifact_id`, `artifact_url`, `completed_at_utc` and `expires_at_utc`.
- `DOWNLOADED_NOVELS.md` is the generated human-facing view of that history, grouped by website.
- `novel_sources.json` is a small curated list for resolving saved titles that are not yet in the completed registry. It does **not** contain the novel content.

The registry holds **metadata and links only**. The actual chapter text and EPUB live in GitHub Actions artefacts while available, or in user-controlled local storage after download.

### “Already downloaded” is a time-bound status

`tools/download_registry.py` provides `canonical_url()`, `normalise_range()`, `available_ranges()` and `already_available()`:

- A completed entry with an expired or unparsable expiry timestamp is **not an available cache hit**.
- `range: "all"` covers any requested subrange while the artefact is still available.
- Multiple valid completed ranges can collectively cover another requested range if there are no gaps.
- An incomplete or failed item cannot satisfy a skip check.
- History entries should remain visible even after artefact expiry.
- Registry availability does not verify a copy stored elsewhere on the user's PC; the Windows downloader separately checks local ZIPs.

Do **not** delete expired history in an attempt to “fix” redownloads. Do **not** equate a past run ID with durable storage.

### Safe publication under concurrency

`tools/publish_registry.py` is deliberately not a naive read-then-push of stale JSON:

1. Fetch the newest `origin/main`.
2. Create a registry update branch from that state.
3. Validate/record the exact newly completed book and artefact.
4. Commit only `downloaded_novels.json` and `DOWNLOADED_NOVELS.md`.
5. Open a metadata-only PR and try to squash-merge it.
6. If another novel's registry PR merged meanwhile, refresh from the latest `main`, rebuild the registry and retry with bounded attempts.
7. If automatic merging is prevented by repository rules, preserve the complete book artefact and provide a link to the pending PR instead of pretending registration succeeded.

Do not replace that algorithm with force-pushing registry files to `main`. A successful download job and a successful registry merge are **distinct outcomes**.

### Artifact lifetimes and privacy

The completed novel and intermediate range artefacts generally have **seven-day retention**. The cover-only artefact has **30-day retention**. These are workflow values that can change; inspect YAML when reporting an exact expiry. In a public GitHub repository, users with appropriate access may be able to retrieve Actions artefacts. Only archive/share works when permitted, and never put private novel contents into commits, test fixtures, generated PR descriptions or comments.

## 10. Windows: retrieve completed artefacts, do not download source chapters

Entry point: `Download-All-Novels.cmd` (repository root).

The CMD delegates to `tools/download_all_artifacts.ps1` under Windows PowerShell 5.1. The PowerShell helper `tools/zip_novel_artifacts.ps1` validates and packages **exactly one expected book** from the downloaded artefact.

Main behaviour:

1. Read the current registry or an explicitly supplied local registry file.
2. Select completed full-book records (`range == "all"`), preferring appropriate available artefacts.
3. Build a local index of existing, internally validated ZIP files, keyed by the novel's source URL rather than ZIP filename.
4. Skip books already present as a valid local ZIP; optionally scan **one specified extra ZIP directory** without changing it.
5. Repack recognised legacy extracted folders without accessing the network when possible.
6. If a real artefact download is required, check `gh` availability and user authentication, then fetch by stored artifact identity.
7. Stage, identify the correct book folder, validate required files/manifests/EPUB and optional cover, and publish one ZIP without overwriting an existing file.
8. Report expired/missing/invalid artefacts and keep a diagnostic transcript.

Key command examples:

~~~cmd
Download-All-Novels.cmd
Download-All-Novels.cmd -ExistingZipDirectory "D:\My Novel ZIPs"
Download-All-Novels.cmd -RepackOnly
Download-All-Novels.cmd -Limit 1
Download-All-Novels.cmd -BrowserLogin
~~~

Non-network launcher self-check:

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\download_all_artifacts.ps1 -CheckSetup
~~~

PowerShell parameters include `Repository`, `Destination`, `MaxAttempts`, `Limit`, `BrowserLogin`, `CheckSetup`, `RepackOnly`, `KeepOriginalFolders`, `RegistryFile` and `ExistingZipDirectory`.

Important local paths and safety contracts:

- Default output: ignored `Downloaded_Novels/`.
- Diagnostic log: ignored `download-last-run.log`.
- Failed items: `Downloaded_Novels/failed-downloads.txt`.
- Original legacy folders are kept/moved to recoverable backup space unless the user explicitly requests otherwise; do not discard them on repack failure.
- An existing corrupt ZIP is an error or conflict, **not a reason to overwrite or delete it**.
- A book folder discovered in a combined historic artefact must match the selected source URL. Never package the first arbitrary `metadata.json` you find.
- A local complete ZIP may have a different filename or artifact ID from the currently recorded one; validate identity from within the package.
- The CMD displays errors and pauses; preserve that behaviour for double-click users.
- Paths with spaces, Windows reserved names, PowerShell 5.1 parameter binding and native-command nonzero exit codes are tested operational requirements.
- `-RepackOnly` should work without network login and should leave invalid originals untouched.

The Windows ZIP helper's validation rules are its own concrete contract. Do not casually broaden accepted filenames or remove checks without tests, even if another producer has a slightly different standalone layout. If supporting new producer output, update compatibility tests deliberately.

## 11. Offline PDF to one-book ZIP

The PDF converter is separate from all website downloaders and is documented in `docs/PDF_TO_NOVEL.md` and `PDF-to-Novel/README.md`.

### Components

- `tools/pdf_to_novel.py`: inspect, detect headings, validate boundaries, collect chapter text, optionally extract a cover, build EPUB, construct a staged ZIP, validate its integrity and write a separate report.
- `tools/pdf_batch.py`: read each PDF in the specified folder; hash to a stable filename; skip existing valid ZIPs; preserve bad existing ZIPs; offer an editable review plan for ambiguous sources.
- `PDF-to-Novel/Convert-PDFs.cmd`: one-click Windows wrapper with relative-folder resolution, rights confirmation, dependency setup and visible pause.

Local folder layout:

~~~text
PDF-to-Novel/
    Convert-PDFs.cmd
    PDFs/               # user-supplied inputs, not committed
    Novels/             # novel-<hash>.zip + separate validation reports
    README.md
~~~

Advanced commands:

~~~powershell
python -m tools.pdf_to_novel "D:\Books\Story.pdf" --inspect --output-dir "D:\Books\Review"
python -m tools.pdf_to_novel "D:\Books\Story.pdf" --boundaries "D:\Books\Review\pdf-chapter-plan.json" --expected-chapters 120 --output-dir "D:\Books\Review" --confirm-rights
python -m tools.pdf_batch --confirm-rights
~~~

The converter works only on **selectable-text PDFs**. Image-only/scanned input fails closed; there is no OCR or network fallback. The source file must not be modified or deleted.

### Chapter detection and fidelity

- Preserve one-based source page and non-empty line positions.
- Support source-derived chapter headings including numbered chapters, prologue and epilogue.
- Respect manually reviewed heading overrides in a boundaries JSON file.
- Distinguish display headings from story text; avoid skipping body lines.
- Honour the source's actual line coverage, chapter order, start/end positions, paragraph grouping and warnings.
- Report missing/duplicate chapter numbering, ambiguous headings, suspicious short chapters, OCR-unreadable pages and unverified synopsis.
- Preserve original Chinese Unicode; only expand known presentation ligatures. Do not introduce broad aggressive text normalisation.
- Do not invent missing chapters, correct fictional prose, fabricate authors or create unsourced synopsis text.
- The validation report is deliberately **outside** the ZIP.

### PDF identity, limits, and publication

- Use streamed SHA-256 of the original PDF for stable file identity. `source_url` is `pdf://sha256/<digest>`.
- Standard output name: `novel-<first-12-hex-of-PDF-SHA256>.zip`.
- The converter guards against inputs larger than **1 GiB** or **50,000 pages**, and caps parsed chapter count at **20,000**.
- EPUB generation and PDF-page analysis still consume memory proportional to the novel. The code avoids some unnecessary whole-file copying, but is **not fully streaming**.
- Before publishing, write to a temporary ZIP in the destination folder; verify ZIP CRC, files, chapter hashes, ordering, word counts and EPUB spine.
- `--replace` must be explicit for intentional same-identity ZIP replacement.
- The batch wrapper skips an existing *valid* ZIP; it does not overwrite an existing *corrupt* ZIP.
- The user should inspect the validation report and selected first/middle/last chapters before downstream upload.
- The PDF ZIP's internal validation does **not** automatically prove acceptance by a separate Hugging Face dataset uploader.

## 12. Local EPUB conversion for other authorised sources

`tools/import_local_epub.py` is a **network-free** converter for EPUBs already supplied by the user with the necessary rights. It recognises strict permitted source-URL shapes for **Royal Road**, **WTR-Lab** and **Scribble Hub**. This offline importer is separate from the author-verified cross-post internet retriever described below. A source URL labels the output's identity; the program does not fetch the EPUB from that URL.

Example:

~~~powershell
python -m tools.import_local_epub --epub "My Author Export.epub" --source-url "https://royalroad.com/fiction/21220/mother-of-learning" --output-dir Imported_Novels --confirm-rights
~~~

That URL is a formatting example, **not** permission to archive that particular book.

Safety checks include:

- Source EPUB exists, is a real ZIP/EPUB, has usable title/chapters and passes CRC checks.
- Input EPUB compressed size no greater than **300 MiB**.
- Aggregate declared expanded size no greater than **750 MiB**.
- Any individual EPUB member no greater than **30 MiB**.
- At most **20,000 chapters**, with a limited additional budget for non-chapter EPUB members.
- Publish one ZIP with identity-derived `novel-<URL-SHA256-prefix>.zip` filename.
- Verify the copied EPUB, chapter counts, source URL, SHA-256 chapter TXT members, expected files and optional image format before replacing output.
- Use temporary/staged output; do not overwrite an existing ZIP without explicit `--replace`.

The generic `novel_downloader.py --import-epub` mode is distinct from this ZIP packager: it exports a book directory, checks title collisions and supports deliberate `--overwrite`. **Do not conflate the two interfaces or their overwrite flags.**

## 13. Covers and synopsis preservation

### Covers inside new novels

New NovelFull outputs may take a source EPUB's embedded cover; FreeWebNovel may use a publicly accessible book-page image. `tools/novel_covers.py` validates type, dimensions, public source restrictions and size before returning optional cover data. JPEG and PNG are the normal output extensions; supported conversions can produce JPEG from WebP/GIF.

Important controls visible in the code: maximum original image bytes **8 MiB**, maximum pixel count **20 million**, and rejection of obviously non-public image URLs. Cover embedding is optional and must not affect verified chapters or their hashes.

### Existing novels: image-only collection

`tools/download_covers.py` reads the completed-download Markdown index and fetches **only covers**, without fetching chapters or modifying old archives. The cover-only workflow (`.github/workflows/download-covers.yml`) produces an artefact such as:

~~~text
NovelFull/example-book-<8-char-url-hash>.jpg
FreeWebNovel/another-book-<8-char-url-hash>.png
covers_manifest.json
~~~

The stable URL digest avoids title collisions. The tool supports dry-run, website selection, limit, force and a controlled request delay. Successful output goes to ignored `Downloaded_Covers/`. Covers are **not retrofitted into existing novel ZIPs** by the image-only downloader.

### Synopses, genres and publication status

- `novel_downloader.epub_chapters()` reads sourced EPUB `dc:description` and exposes readable description/synopsis when present.
- `tools/epub_source_metadata.py` reads OPF-only source genres and recognised publication status.
- `tools/chunked_download.py` preserves description/genres/status through final EPUB rebuild and verifies the result.
- Legacy NovelFull range artefacts lacking newer metadata pipeline flags are deliberately rejected for reuse when they could drop metadata.
- A genuinely absent synopsis, cover, genre or status is **missing input**, not a reason to write AI-generated replacement metadata into the source record.

### Existing novels: validated synopsis repair

`tools/repair_synopsis.py` supports read-only preview by default and `--apply` for a deliberate repair. It can use an explicitly provided description or fetch a public **NovelFull book information page only**, not novel chapters.

For `--apply`, stage a modified ZIP, check the new EPUB and JSON, and verify the original chapter payloads and manifest are preserved. If it fails, keep the original untouched. This is an **in-place validated replacement, not a permanent separate backup**; users needing undo must keep their own copy.

Examples:

~~~powershell
python -m tools.repair_synopsis --zip "Downloaded_Novels\novel-example.zip"
python -m tools.repair_synopsis --zip "Downloaded_Novels\novel-example.zip" --apply
python -m tools.repair_synopsis --directory "Downloaded_Novels"
~~~

It does not automatically update the hosted reading application or private dataset after a local repair. That is a separate downstream import/update operation.

## 14. Experimental or restricted source support: do not silently expand scope

Different sites have different technical and permission restrictions. A parser existing in `tools/` does **not** mean automated whole-book download support is approved.

| Site or input | Current role in this repository | Safe boundary |
| --- | --- | --- |
| NovelFull | Production FanFicFare-backed bounded downloader | Authorised HTTPS source, verified range assembly |
| FreeWebNovel | Separate production public-page range downloader | Sequential requests, restrictions respected, missing chapters fail closed |
| Royal Road | Offline feasibility and authorised local EPUB import | No enabled live GitHub bulk downloader here |
| WTR-Lab | Offline feasibility and authorised local EPUB import | No automated website downloader enabled |
| Scribble Hub | Authorised offline EPUB import; **one** verified same-author FFN cross-post via FicHub | Direct Scribble Hub HTTP 403; no general site downloader or bulk menu |
| Novel Fire | Offline saved-HTML feasibility only | No automated novel crawling; respect published restrictions |
| Light Novel Pub | Offline saved-HTML feasibility only | No full downloader enabled |
| WebNovel | Read-only public metadata, HTTP/browser feasibility, constrained two-public-chapter tests, authorised saved-page/JSON/TXT imports | No unrestricted WebNovel all-chapter downloader, no locked content or challenge bypass |
| Local selectable-text PDF | Production offline conversion | Source review, no OCR |
| Authorised local EPUB | Production offline conversion | Source identity and archive validation |

### Author-verified Scribble Hub cross-post through FicHub

`tools/verified_crosspost_download.py` is a **narrow, internet-enabled** route, distinct from both the direct NovelFull/FreeWebNovel downloaders and the network-free `tools/import_local_epub.py`:

- The user provides the original Scribble Hub **series** URL and `--confirm-rights`; no local EPUB is required. The command is `python -m tools.verified_crosspost_download "<scribble-hub-series-url>" --confirm-rights`.
- `tools/verified_crossposts.json` is an explicit author cross-post allowlist. Currently it contains only Scribble Hub series `445037`, by MonkWithAPen, cross-posted by the same author as FanFiction.net story `14031894`. **Never** infer the mirror for an unrelated series simply from a similar title.
- The dedicated manual [`.github/workflows/scribblehub-download.yml`](.github/workflows/scribblehub-download.yml) uses the validated cross-post CLI and `tools/verified_crosspost_artifact.py` to convert the validated ZIP to the **standard** book folder before `upload-artifact`. It runs the existing registry check and `tools.publish_registry`, and avoids publishing a nested ZIP. It has a mandatory authorisation checkbox and rejects unregistered novel IDs. Artefacts on public repositories may be publicly accessible.
- The downloader calls FicHub's documented `/api/v0/epub` and its same-host EPUB cache, **not** Scribble Hub's pages or the protected chapter AJAX endpoint. Source URL validation, story author/title/FFN numeric ID, reported count, first-chapter title and a numbered checkpoint are fail-closed.
- The 14 November 2026 remote test found **432** author-posted story chapters and a FicHub EPUB containing **two non-story introductory sections plus 432 actual chapters**. The code excludes only the two registered front sections when the verified first story chapter follows. If this structure or count changes unexpectedly, stop rather than silently shift chapters.
- Preserve cover and EPUB description if present, reconstruct a clean EPUB with exactly the story chapters, and call the **existing** `import_epub_to_zip` to stage and verify chapter SHA-256, EPUB integrity, ZIP CRC, metadata and stable Scribble numeric-ID identity. The command publishes to `Downloaded_Novels/` and requires `--replace` for updating an existing ZIP.
- FicHub's API is unstable and may be temporarily rate-limited or stale. Use a custom project User-Agent with contact; perform at most one export request plus one ebook request per operation; **no concurrent calls or automatic retries**. Do not expose or commit story text or upload the ebook into a public CI artefact.
- Tests in `tests/test_verified_crosspost_download.py` and `tests/test_verified_crosspost_artifact.py` use wholly synthetic EPUB fixtures and injected fake HTTP clients; they cover provenance, chapter completeness, front-matter exclusion, bad URL handling, rights, failed requests and rollback. Keep NovelFull and FreeWebNovel regressions green.

This route is also reused by the unified bulk workflow for authorised, registered cross-posts. It does **not** mean Scribble Hub's direct HTTPS chapter requests can be automated reliably. Unknown series IDs must fail with a clear explanation until another same-author cross-post is independently verified and registered.

### WebNovel modules

- `tools/webnovel_probe.py`: one public book metadata page, no chapter harvesting.
- `tools/webnovel_http_diagnostics.py`: one request and safe status/header diagnostics, no response body persistence.
- `tools/webnovel_browser_probe.py`: ordinary temporary Chromium browser feasibility; public book plus at most two chapter pages; no stealth/session import or challenge bypass.
- `tools/webnovel_public_two_chapter.py`: at most one public book page and two public chapter pages, only when access and rights allow.
- `tools/webnovel_export.py`: offline export of at most two user-supplied authorised chapter records.
- `tools/webnovel_saved_pages.py`: offline import of one or two locally saved authorised HTML/TXT chapter files.
- `tools/webnovel_bulk_import.py`: offline bulk import of up to **10,000 consecutively numbered** locally saved authorised chapters, with `--dry-run`, optional ranges and verified `--resume` state.
- `tools/WEBNOVEL_*.md`: instructions and precise limitations for each stage.

Do not infer from the bulk **local file import** that the project can fetch 10,000 WebNovel chapters. Importing user-held files and scraping a remote service are fundamentally different actions.

### Adding a genuinely new website

Before writing any live downloader:

1. Establish that the specific site's terms and permissions support the intended archiving.
2. Identify public canonical book paths, chapter numbering, metadata sources and access boundaries.
3. Build a **separate** offline HTML parser/fixture test with at most a small, authorised sample.
4. Reject access challenges, locked pages, unexpected redirects, empty chapter bodies, duplicates and missing numbers.
5. Add a dedicated adapter/module and bounded acquisition mechanism **only when justified**.
6. Prove stable source identity, chapter count, range checks, reproducible EPUB/ZIP export and full rollback behaviour.
7. Extend the existing **unified** bulk workflow rather than adding redundant bulk menus.
8. Run all NovelFull and FreeWebNovel regressions to prove the old pipelines remain unchanged.
9. Never use login automation, proxy rotation or content unlocking to make a prohibited source “work”.

## 15. GitHub Actions workflow catalogue and security

| Workflow | Trigger | Primary jobs | Output / side effects |
| --- | --- | --- | --- |
| `.github/workflows/ci.yml` | Push and PR | Ubuntu unit/synthetic pipeline; Windows smoke; Windows ZIP packaging | Test outputs only; short-lived synthetic artefact |
| `.github/workflows/pdf-conversion-ci.yml` | Relevant PR/push paths and manual dispatch | Ubuntu + Windows Python 3.12 PDF tests | Offline synthetic outputs |
| `.github/workflows/download-novel.yml` | Manual and reusable call | Prepare, bounded chapter batches, assemble, report | Temporary book artefacts and metadata registry PR |
| `.github/workflows/freewebnovel-download.yml` | Manual and reusable call | Prepare, bounded chapter batches, assemble, report | Temporary book artefacts and metadata registry PR |
| `.github/workflows/scribblehub-download.yml` | Manual and reusable call | Explicit rights gate, verified same-author FicHub cross-post, archive verification | Temporary complete novel artefact and metadata-only registry PR |
| `.github/workflows/scribblehub-download.yml` | Manual only | Verify rights and registered author cross-post, FicHub export, ZIP validation, artefact assembly and metadata registry | Seven-day complete-novel artefact and metadata-only registry PR; only allowlisted same-author cross-posts |
| `.github/workflows/library-bulk-download.yml` | Manual | Resolve selections, three site-specific reusable workflows, always-run recovery summary | Delegates to site workflows; publishes an additional partial-success recovery artefact even if other jobs fail |
| `.github/workflows/download-covers.yml` | Manual | Cover-only job | 30-day cover-image artefact; no chapter or registry edits |

Security/operational expectations:

- Workflow actions are pinned to reviewed **full commit SHAs**, not only mutable major tags.
- Workflows use Python 3.12 resolved dependency locks.
- CI's default permissions are read-only. Write/pull-request permissions appear only where publishing a metadata PR needs them.
- Never interpolate untrusted user text into a shell command without safe quoting/argument handling.
- Keep source URLs in environment variables or correctly quoted argument vectors. Do not use `shell=True` for downloader processes.
- Keep chapter content out of commit diffs, summaries and debug logs. Book artefacts can be accessible to other users of a public GitHub repo.
- No secrets or PATs should be embedded in tracked files; GitHub workflows use their available temporary token where authorised.
- When changing a reusable workflow, test both invocation paths: manual dispatch **and** Library - Bulk Download. Scribble Hub is now available through the single bulk menu only for explicitly verified same-author cross-posts with rights confirmation; no general Scribble Hub site scraping or unrestricted bulk coverage is implied.
- Do not remove mandatory CI jobs just because an intermittent live-site request is unavailable.
- External metadata-only NovelFull checks are **non-blocking** by design. Offline fixtures are the release gate.

## 16. Test map and minimum verification gates

### Core test collections

| Test file or collection | Focus |
| --- | --- |
| `tests/test_novel_downloader.py` | EPUB extraction, metadata, URL checks, direct chapter ranges, cache identity, imports, staged export and rollback, progress/checkpoints |
| `tests/test_chunked_download.py` | Batch planning, counts, piece identity, complete/reused artefacts, assembly, synopsis/cover/genre metadata |
| `tests/test_download_registry.py` | Canonical URL and range handling, expiry and completed record logic |
| `tests/test_publish_registry.py` | Latest-main metadata publishing, merge races and retry behaviour |
| `tests/test_library_bulk.py`, `tests/test_bulk_download.py` | Name/URL selection, website grouping, deduplication, error handling |
| `tests/test_freewebnovel_probe.py`, `tests/test_freewebnovel_downloader.py` | Public-site parser, boundaries, lock/challenge detection and complete ranges |
| `tests/test_epub_source_metadata.py` | OPF description/genre/status extraction |
| `tests/test_novel_covers.py` | Cover limits, safe book/image URL policy, EPUB cover handling |
| `tests/test_import_local_epub.py` | Offline, verified EPUB-to-ZIP import |
| `tests/test_repair_synopsis.py` | Synopsis repair integrity and dry run/apply |
| `tests/test_source_feasibility.py` | Offline parsing for investigated sources |
| `tests/test_webnovel_*.py` | Separate WebNovel restricted/authorised import and feasibility behaviour |
| `tests/test_zip_packaging_windows.py`, `tests/cover_zip_smoke.ps1` | Portable ZIP compatibility, Windows processing, covers |
| `tests_pdf/test_pdf_to_novel.py` | PDF heading extraction, source fidelity, hashes, ZIP/EPUB integrity, source budgets |
| `tests_pdf/test_pdf_batch.py` | Multiple PDFs, non-destructive skips/failures and Windows one-click CMD |

### Standard test commands

~~~powershell
python -m pip install -r requirements.lock
python -m pip check
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p test_novel_downloader.py -v
python -m unittest discover -s tests -p test_chunked_download.py -v

python -m pip install -r requirements-pdf.lock
python -m unittest discover -s tests_pdf -p "test_pdf_*.py" -v
~~~

Run the relevant narrow suite while developing, **then all affected suites**, then check the workflow matrix. The Windows tests are indispensable when modifying PowerShell, CMD, filenames, path handling, line-endings or ZIP packaging.

### Non-negotiable regression scenarios

Changes to the relevant subsystem should prove all applicable cases:

- Two books whose URLs have the same terminal path do not overwrite each other.
- Same-title EPUB imports do not clobber different books by default.
- Explicit custom slugs cannot subvert source identity checks.
- A forced re-download failure or chapter count mismatch leaves a previously published book intact.
- A staging/rename failure rolls back to the complete previous generation.
- A process-interrupted export backup can be recovered on retry.
- Untracked `chapter_9999.txt` files survive an unrelated export; only previously tracked tool-owned chapter files are cleaned.
- Exact inclusive chapter ranges have no holes or repeated positions.
- Each range's file names, byte hashes, source identity and optional cover remain consistent.
- Cached artefacts are reused only after validation, not merely because a name exists.
- Source EPUB description/genres/status and optional covers survive final batch assembly.
- Missing descriptions/covers remain absent rather than being invented.
- A PDF with inaccessible text, bad boundaries, duplicate chapter identities or size/page-budget violations fails without publishing a bad ZIP.
- A good existing ZIP is skipped; an invalid existing ZIP is preserved for investigation.
- The Windows launcher handles whitespace paths, PowerShell 5.1 syntax, startup checks and visible nonzero error codes.
- Registry updates do not lose another novel's download record when multiple workflows finish concurrently.

### Evidence standard

A green unit suite means **the exercised behaviours passed**, not that real websites are stable. Describe findings accurately:

- **Confirmed by deterministic test**: e.g. synthetic four-chapter EPUB assembly.
- **Confirmed by checked source**: e.g. URL validation or known workflow limits.
- **Requires live verification**: e.g. current chapter selectors, access controls or complete remote catalogue.
- **Not verified here**: e.g. private dataset acceptance or long-term remote archive durability.

Avoid the overstatement “nothing can break”. Use targeted regressions, meaningful failures and explicit residual risk.

## 17. How an AI agent should approach changes

### Before editing

1. Read this file, then `README.md` and the focused guide for the component.
2. Check current `main`, open PRs, active workflow runs and latest related changes. Do not assume the baseline commit shown above is still current.
3. Identify the exact entry point, source module, orchestration workflow, output format, downstream consumer and affected tests.
4. Determine whether the requested operation is **read-only**, **local data-writing**, **network-fetching**, **GitHub publishing**, or **destructive**. Do not blur those categories.
5. Confirm whether the affected feature is established production, locally enabled only, or restricted feasibility.
6. Write down the invariants most likely to regress, especially identity, chapter count, filename formats and original-data preservation.
7. Check for current artefacts/records that must remain backward-compatible.

### During implementation

- Prefer a focused topic branch and a narrow PR; do not mix refactors of unrelated adapters.
- Change the smallest coherent part of the system, but follow data-contract changes through every producer, validator, registry writer and Windows consumer that handles them.
- Add regression tests for both normal success and failure/rollback behaviour.
- Use fixtures made from original synthetic prose, tiny legal/public-domain samples or mocked HTTP responses. Avoid placing real copyrighted novel text into Git.
- Keep existing functioning download logic and original source-site integrations unchanged unless directly necessary.
- Prefer offline, dependency-injected tests over automatic live requests.
- Avoid temporary workflow generators or diagnostic files remaining on `main` after completion.
- Verify output names, source identity, chapter manifests, EPUB spine, image metadata and SHA-256 contracts end to end.
- Keep lockfiles, README and this handbook in sync with actual changes.

### Before merging or closing a task

- Inspect the diff to ensure **only intended files changed** and no novel text, token or personally sensitive data was committed.
- Run narrow tests, full applicable offline test suite, and both platform matrices where applicable.
- Confirm GitHub Actions has concluded **success**, not merely started or queued.
- Treat a non-blocking failed live metadata smoke differently from a failed deterministic unit test; investigate but do not falsify the status.
- Review PR base/head freshness, successful checks and merge status.
- After merging, verify `main` points to the expected commit and its post-merge workflows pass.
- Do not claim that downstream cloud storage, authentication or real full-book downloads were exercised unless they truly were.
- Summarise changes, test evidence, remaining caveats and any operator action clearly.
- Do not alter or delete unrelated branches, artifacts, datasets or files unless explicitly part of the requested work.

### Review priorities

When time is constrained, prioritise:

1. Preventing loss or misattribution of an existing novel.
2. Preserving complete and correctly ordered chapter/manifest/EPUB outputs.
3. Keeping site access within explicit user permissions and the source's constraints.
4. Preserving Windows retrieval and historical archive compatibility.
5. Preserving recoverable partial work and valid completed artefacts.
6. Eliminating reproducibility drift and CI failures.
7. Improving documentation and operational ergonomics.

## 18. Typical user tasks and the files to inspect

| User request | Start here | Validation |
| --- | --- | --- |
| “A downloaded book has wrong chapters or a missing range” | `novel_downloader.py`, `tools/chunked_download.py`, `tools/download_registry.py` | Exact source/range identity, every position, EPUB spine, source metadata |
| “My previous EPUB was overwritten or the wrong book reused” | `novel_downloader.py` | Collision tests, failed forced refresh, rollback |
| “A large NovelFull download times out” | `.github/workflows/download-novel.yml`, `tools/chunked_download.py`, `fff_progress_runner.py` | Resume/reuse valid ranges; incomplete batches never register |
| “FreeWebNovel gives the wrong chapter” | `tools/freewebnovel_downloader.py`, `tools/freewebnovel_probe.py` | Number/title/body checks; no auto bypass |
| “Add another bulk option” | `tools/library_bulk.py`, `.github/workflows/library-bulk-download.yml` | Reuse single grouped bulk menu; no duplicate workflow |
| “Why is a book not in DOWNLOADED_NOVELS.md?” | `tools/publish_registry.py`, `tools/download_registry.py` | Check artefact success versus registry PR state |
| “Why does downloaded novel ZIP not appear locally?” | `tools/download_all_artifacts.ps1`, `tools/zip_novel_artifacts.ps1` | Existing ZIP scan, expired artifact, correct nested book, local log |
| “Abe the Wizard / historic bulk artefact contains extra directories” | `tools/zip_novel_artifacts.ps1` | Exact source metadata, only one correct book ZIP |
| “Make a PDF usable by the reader” | `tools/pdf_to_novel.py`, `tools/pdf_batch.py`, `docs/PDF_TO_NOVEL.md` | Boundary report, TXT fidelity, ZIP+EPUB validation |
| “Convert my already-authorised EPUB” | `tools/import_local_epub.py` | Source URL identity, ZIP safety budgets, no silent overwrite |
| “New novels have no synopsis/genre” | `tools/epub_source_metadata.py`, `tools/chunked_download.py` | Source OPF metadata and final EPUB/JSON equality |
| “Old novel ZIP is missing synopsis” | `tools/repair_synopsis.py` | Dry-run first; chapter-manifest preservation |
| “Download only covers” | `tools/download_covers.py`, `tools/novel_covers.py` | Only images; no novel archive mutation |
| “Automate downloading from WebNovel, WTR-Lab, Novel Fire etc.” | `docs/experimental-sources.md`, the specific feasibility modules | First verify permission; do not bypass site restrictions |
| “CI failed on Windows” | `.github/workflows/ci.yml`, PowerShell scripts, Windows test files | PS5.1 parse/parameter rules, paths with spaces, exit status |

## 19. Troubleshooting and expected failure semantics

### Download reports success but appears incomplete

Check whether this was a **direct whole-book CLI** run without `--expected-chapters` or a **bounded Actions** run. Direct mode may have lacked an authoritative external count. For Actions, inspect plan total and selected bounds, complete batch manifests, final assembled `chapters.json` and the EPUB spine. A short or missing chapter must be a failure, not “completed with warnings”.

### A batch re-downloads despite an earlier run

The old artefact may be expired, absent, corrupt, missing the exact range, tied to another source, or missing newer metadata pipeline capabilities. That is intentional. Inspect `reuse_complete_piece()` diagnostics rather than deleting cache checks to save a download.

### A book is in the registry but cannot be downloaded

The registry preserves history after the temporary GitHub artefact expires. Check `expires_at_utc` and GitHub's actual artefact state. If an authorised local ZIP already exists, retain it. The registry is not remote long-term book storage.

### Registry PR did not merge

The book artefact can exist even when metadata publishing is blocked. Inspect the publisher's PR link, branch permissions, GitHub Actions permission to create PRs, merge conflicts and retry logs. Do not record success unless the registry was actually updated.

### A ZIP exists but the Windows downloader does not skip it

The ZIP may not be the expected one-book structure, may have wrong `source_url`, missing EPUB, mismatched manifest, extra unrelated folders or invalid cover. Validate the **contents**, not just the name. Do not overwrite or delete the ZIP simply to suppress the error.

### A PowerShell CMD launcher closes or shows a parameter error

Run `-CheckSetup` first and inspect `download-last-run.log`. Review syntax under **Windows PowerShell 5.1**, not only `pwsh`. Paths must resolve relative to the script and preserve spaces. The CMD's exit status and pause path are intentional.

### The PDF converter refuses a book

Common causes: scanned/image-only pages; no reliable chapter boundaries; missing title/author metadata; numbered gaps; source headers/footers confusing detection; password protection; or the configured resource limits. Use `--inspect` and a manually reviewed boundaries file if appropriate. Never fill missing prose with generated content to force a pass.

### A novel has no cover or synopsis

Not all sources supply those fields. Confirm that the source OPF/book page actually contained them; check metadata pipeline flags on cached ranges and the final EPUB/JSON. Do not hallucinate source data.

### A restricted website responds with 403 or a challenge

Stop. Diagnostic failure is a valid result. Do not automatically retry, spoof an authorised session, use a solver, rotate proxies or expand to hidden APIs. Read the relevant feasibility document before changing site support.

## 20. Known limitations and deliberate trade-offs

These should remain explicit when discussing the project or proposing future work:

1. **No universal completeness guarantee from direct downloads without a known expected count.** The batch workflow is stronger because it discovers and verifies bounds.
2. **Live-site behaviour changes.** FanFicFare adapters, FreeWebNovel HTML selectors, website permissions, redirects and catalogues can change independently of this repo.
3. **Input URL hardening is not a complete network security sandbox.** Avoid presenting it as proof that every DNS resolution, redirect or adapter internal request cannot reach private destinations.
4. **Staged directory replacement is recoverable, not globally atomic.** A crash between renaming the old and new directories can leave a recoverable backup for the next invocation.
5. **A green offline CI run is not a completed real-novel download.** The optional live metadata-only check is neither a rights grant nor a chapter-text acceptance test.
6. **Python lockfiles pin versions, not distribution hashes.** Upstream artefact integrity still depends on package sources and runtime environment.
7. **GitHub Actions artefacts expire.** Local verified ZIP copies or other authorised storage are needed for retention beyond their lifecycle.
8. **Cover-only retrieval does not rewrite old ZIPs.** Synopsis repair is a separate explicit action.
9. **PDF extraction is not OCR, proofreading or guaranteed layout recovery.** Human review of warnings and chapter samples remains necessary.
10. **Other source modules are research or local import only.** WebNovel, WTR-Lab, Royal Road, Novel Fire and Light Novel Pub do not automatically become supported hosted download choices.
11. **Separate downstream repositories may enforce stricter validation or different upload limits.** Test integrations there; do not claim this repo controls their behaviour.
12. **Copyright and site permission constraints remain external prerequisites**, regardless of technical feasibility or how many unit tests pass.

## 21. Documentation cross-reference

When changing a subsystem, also consult the relevant living guide:

- `README.md`: general operation and latest end-user instructions.
- `PDF-to-Novel/README.md` and `docs/PDF_TO_NOVEL.md`: one-click Windows conversion, boundary overrides and validation reports.
- `docs/experimental-sources.md`: detailed decisions and restrictions for Novel Fire, Light Novel Pub, WTR-Lab and Royal Road.
- `tools/FREEWEBNOVEL_FEASIBILITY.md`: initial FreeWebNovel two-chapter compatibility research.
- `tools/WEBNOVEL_BROWSER_PROBE.md`: ordinary browser feasibility and challenge stop conditions.
- `tools/WEBNOVEL_PUBLIC_TWO_CHAPTER.md`: bounded public chapter probe.
- `tools/WEBNOVEL_SAVED_PAGE_IMPORT.md`: offline one/two saved HTML/TXT chapter input.
- `tools/WEBNOVEL_EXPORT.md`: offline user-provided JSON-to-EPUB/TXT feasibility.
- `tools/WEBNOVEL_BULK_IMPORT.md`: offline, validated/resumable bulk import of saved local chapters.
- `DOWNLOADED_NOVELS.md`: generated historical registry view.

## 22. Concise final rules for coding agents

> **Preserve source identity. Verify every expected chapter. Protect existing novel data. Never mistake a checkpoint for a finished book. Respect source-site permissions. Keep real novel text out of Git. Maintain both Windows and Linux compatibility. Test offline first. Keep the single bulk workflow. Do not silently expand experimental source capabilities. Do not declare a deployment, merge, download or CI result successful until it is confirmed.**

This handbook is designed to lower the cost of understanding a large, interconnected personal utility project. It is intentionally detailed, but it remains **documentation**: the latest executable source, workflow definitions, tests and explicit operator requirements take precedence whenever reality changes.
