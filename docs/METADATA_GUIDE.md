# Covers, synopsis, metadata and archive maintenance

Detailed maintenance instructions moved out of the short [README](../README.md). This document explains optional images, sourced descriptions, older ZIP repair, and the difference between local files and separately hosted library records.

Other guides: [Supported websites](WEBSITE_SUPPORT.md) · [Downloading and Windows](DOWNLOAD_GUIDE.md) · [PDF conversion](PDF_TO_NOVEL.md) · [AI agent handbook](../AGENTS.md).


## Novel covers and image-only downloads

**New future downloads:** The NovelFull downloader extracts the original
EPUB's cover image (when present). FreeWebNovel obtains its cover from the
public novel information page where available. Covers are validated before
use and remain optional. Chapter ZIP archives include a standalone `cover.jpg`
or `cover.png`, a `cover_image` filename in `metadata.json`, and an EPUB
with a proper cover image and cover-page metadata. The chapter TXT files,
chapter hashes and existing ZIP identity remain unchanged. Coverless sources
continue to work.

**Existing completed novels, images only:** In **GitHub Actions**, select
**Covers - Download**, choose All, NovelFull or FreeWebNovel, choose the
optional limit (0 = all), and confirm you have permission to save the images.
The Action reads [DOWNLOADED_NOVELS.md](../DOWNLOADED_NOVELS.md) and downloads
**only cover images**. It does not retrieve or change chapters, EPUBs,
existing ZIPs or the registry. The resulting **novel-cover-images**
downloadable Actions artifact (30-day retention) contains:

~~~text
NovelFull/martial-world-<8-character-ID>.jpg
NovelFull/true-martial-world-<8-character-ID>.png
FreeWebNovel/the-first-order-<8-character-ID>.jpg
covers_manifest.json
~~~

The ID is the first eight hexadecimal characters of the SHA-256 hash of
the source book URL, making filenames repeatable across runs and distinct
even when books have identical names. The manifest records title, source URL,
website, novel ID, relative cover filename and success/skip/failure state.
Multiple ranges of the same title are deduplicated.

To download images to your Windows laptop instead, run these commands from
the repository root:

~~~powershell
git pull
python -m pip install -r requirements.txt
python -m tools.download_covers --dry-run
python -m tools.download_covers --confirm-rights
~~~

The third command previews all selected titles and performs no network
requests. The final command saves images to `Downloaded_Covers` and writes
a JSON manifest; existing, valid images are skipped. Use
`--website NovelFull`, `--website FreeWebNovel` or `--limit 5` to select a
subset, and `--force` to replace an existing cover after validation.

The standalone image-only script **does not retrofit the covers into old
novel ZIPs**: that would be a separate archive-repair operation. Only
cover images from publicly readable book information pages are attempted;
blocked, unavailable, missing or invalid images are reported rather than
fabricated or substituted. Images can be copyrighted; save only images you
are authorised to archive. In a public GitHub repository, Actions artifacts
may be visible to other users. Embedding the image in a ZIP does not by
itself enable cover display in Taiyou's Personal Library frontend.

## Synopsis metadata in EPUB and ZIP archives

NovelFull's FanFicFare adapter reads each book's public description and can
store it in the source EPUB as `dc:description`. The download pipeline now
preserves this information through chapter-range exports and the final
reassembled EPUB. Both `source.epub` and `metadata.json` include the
description; the JSON also offers a `synopsis` alias for library readers.
Books whose source does not supply a description are left blank rather than
given fabricated text. The preservation fix applies to **newly created**
download artifacts; it does not rewrite existing GitHub artifacts.

NovelFull chapter batches now carry a synopsis-preserving pipeline version.
If GitHub Actions finds a cached batch created **before** that fix, it will
reject that cached batch and download the range afresh instead of reusing
metadata that may have lost the synopsis. New-format batches remain reusable.
This check does not affect FreeWebNovel. If the original source itself lacks
a description, the assembled novel still cannot have a source synopsis;
the assembly logs a visible warning rather than inventing one.

Previously completed ZIP artifacts remain unchanged. To redownload an
already registered novel, select **Force** in its single download action,
or use the ZIP synopsis repair command below to avoid downloading chapters.

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

## Archive conventions and boundaries

A verified book normally includes:

~~~text
<novel-folder>/
    metadata.json
    chapters.json
    source.epub
    chapter_*.txt
    cover.jpg             # optional; cover.png is also supported
~~~

The `chapters.json` entries specify the actual chapter filenames, order and SHA-256 values. The source URL (or a stable PDF SHA-256 identity for locally converted PDFs) is stronger than a book title or ZIP filename.

**Important distinctions:** The download registry records URLs, chapter ranges and temporary GitHub Actions artefact references; it does not itself store EPUB content. The `Downloaded_Novels/` directory is a user-local output. No command here automatically uploads content to a separate private dataset or changes a hosted reading application's imported records.

Do not silently overwrite a good novel archive. Use explicit `--apply`, `--force` or `--replace` only for the specific operation documented by the relevant tool. Keep your own backup if you need to undo an intentional in-place repair.
