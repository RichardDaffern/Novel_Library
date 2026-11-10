# Next-site feasibility: Novel Fire and Light Novel Pub

**Status: research and isolated, offline parsing only. No new live downloader is enabled.**
Last reviewed: 10 November 2026.

This evaluation does not change the stable NovelFull or FreeWebNovel download
pipelines, downloaded registry, cover ZIP formats, or the unified bulk job.

## Source observations and limitations

| Candidate | Observed public URLs and catalogue | Important constraint | Decision |
|---|---|---|---|
| Novel Fire (novelfire.net) | Public book pages use `/book/<slug>`; `/book/<slug>/chapters` lists numbered links such as `/book/martial-world/chapter-1` and `chapter-2`, with paginated indexes | Its own published terms prohibit crawling/scraping and reserve archive exceptions for public search indexing; automated access may also meet challenges | Do not enable chapter crawling or automatic downloading without verified permission |
| Light Novel Pub (lightnovelpub.com) | Previously indexed novel pages used `/novel/<slug>`, e.g. `/novel/reverend-insanity-05122222` | Site reliability and current chapter URL/content markup could not be verified from live source; permissions and access remain unverified | Do not enable automated chapter downloads until permitted, publicly readable samples have passed validation |
| Light Novel World / old lightnovelpub.org | `lightnovelpub.org` now explicitly says it has shut down and migrated to chikari.moe | It is not interchangeable with `lightnovelpub.com`; the new service is not established as a chapter source | Reject the retired domain rather than silently redirecting or assuming equivalence |

Public source references checked:

- Novel Fire sample book: https://novelfire.net/book/martial-world
- Novel Fire numbered catalogue: https://novelfire.net/book/martial-world/chapters
- Novel Fire terms: https://novelfire.net/page/terms-of-service
- Previously indexed Light Novel Pub: https://lightnovelpub.com/
- Old Light Novel World shutdown notice: https://lightnovelpub.org/

The terms and website layouts can change. Website reachability alone is
not proof that text can or may be downloaded.

## Implemented now

`tools/source_feasibility.py` is an **offline, non-exporting probe**. It
accepts locally saved HTML book/index pages and zero to two locally saved
chapter pages. It can validate supported public book URL shapes, extract
title, author when present, reported chapter count, synopsis availability,
two numbered chapter links, and the length/hash of a verified chapter-text
container. The report contains no chapter prose.

Example for permitted saved Novel Fire pages:

```powershell
python -m tools.source_feasibility "https://novelfire.net/book/martial-world" --book-html "book.html" --index-html "chapters.html" --report "novelfire-feasibility.json"
```

To inspect up to two chapters **only if permitted and already saved**:

```powershell
python -m tools.source_feasibility "https://novelfire.net/book/martial-world" --book-html "book.html" --index-html "chapters.html" --chapter-html "chapter1.html" --chapter-html "chapter2.html" --confirm-rights
```

Replace the book URL with a valid `https://lightnovelpub.com/novel/<slug>`
and use that book's saved pages to test Light Novel Pub. Do not treat old
cached source pages as a successful test of present-day download access.
The tool never requests websites and cannot bypass login/challenges.

## Acceptance criteria before any full downloader

1. Verify an authorised, reachable novel information page and source-specific
   chapter index, with the correct reported chapter count and ordering.
2. Validate exactly two publicly accessible permitted chapters, keeping
   chapter text free of navigation/ads and detecting truncation/locked pages.
3. Check the site's permissions and operational access without evasion.
4. Preserve the exact expected ZIP/EPUB/TXT/metadata/cover schema, including
   synopsis, positions, title, author, hashes and failed-chapter reporting.
5. Add offline fixture-based unit tests on Linux/Windows and a separate
   optional live two-chapter smoke test only when access is permitted.
6. Only then introduce a new, isolated website-specific Actions workflow;
   do not extend an existing NovelFull/FreeWebNovel workflow with unverified
   selectors or backend logic.

Because these conditions are not yet met, current support is **offline
feasibility rather than automated downloads**.
