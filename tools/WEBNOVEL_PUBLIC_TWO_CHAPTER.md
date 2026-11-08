# Public WebNovel chapter feasibility adapter

The independent tool `tools/webnovel_public_two_chapter.py` is a **two-chapter-only public-page feasibility probe**. It is separate from NovelFull and the original metadata-only probe.

## Preconditions

Use it only for chapters that you have confirmed you are authorised to export. It uses public unauthenticated HTML pages only; no cookies, login, premium/locked chapters, private API calls or access-control bypasses. It fails closed on unrecognised page structures.

## Run locally (only after confirming rights)

```bash
python -m tools.webnovel_public_two_chapter "https://www.webnovel.com/book/33422293300201205" --output-dir webnovel-two-chapter-test --confirm-rights
```

When public page content matches the tested format, this creates `chapter-01.txt`, `chapter-02.txt`, `book.txt`, `book.epub` and `metadata.json`. Local outputs should not be committed to Git or redistributed.

This tool makes at most one public book-page request and two chapter-page requests, with no full-novel option and no concurrency. The first two links must be confirmed in numerical order. An unknown layout, access refusal, missing body, or locked-content signal causes an error rather than a bypass.

**Live status:** The offline parser and EPUB/TXT pipeline are covered by synthetic regression tests. Site accessibility and selector stability may vary; passing CI does not prove live retrieval. No live text is included in tests or CI artifacts.

## Test

```bash
python -m unittest tests.test_webnovel_public_two_chapter -v
```

The existing Linux/Windows CI discovers these tests automatically. A live chapter smoke test is intentionally **not** run in GitHub Actions.
