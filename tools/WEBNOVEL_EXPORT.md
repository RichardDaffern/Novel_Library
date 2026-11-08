# WebNovel offline two-chapter export (authorised material only)

This is a separate companion to `tools/webnovel_probe.py`. It is **not** a WebNovel chapter scraper or a downloader. It does not make HTTP requests, read cookies, unlock chapters or access WebNovel accounts. The existing NovelFull downloader and workflows are unchanged.

This is a feasibility tool for material you have permission to export, for example original text you wrote or text supplied with the rights holder's permission. A book being free to read on WebNovel does not itself establish export permission.

## Usage

Prepare a local JSON file called `chapters-authorised.json` (do not commit real chapter text):

```json
{
  "source": "user-supplied-authorised",
  "title": "My Original Story",
  "author": "Example Writer",
  "chapters": [
    {
      "position": 1,
      "title": "Chapter One",
      "text": "This is fictional sample prose written for this example."
    },
    {
      "position": 2,
      "title": "Chapter Two",
      "text": "This is additional original sample prose for chapter two."
    }
  ]
}
```

Then run:

```bash
python -m tools.webnovel_export --input chapters-authorised.json --output-dir webnovel-sample
```

Expected output: `chapter-01.txt`, `chapter-02.txt`, `book.txt`, `book.epub`, and `metadata.json`.

The exporter requires exactly one or two chapters in order. Input files are local only. It rejects unauthorised source markers, missing text, oversized inputs and non-empty output directories.

## Validation and scope

```bash
python -m unittest tests.test_webnovel_export -v
```

The existing GitHub CI runs the tests on Linux and Windows. Tests use original invented chapter fixtures only; no network access or WebNovel chapter text is included. No live chapter download or production WebNovel source integration has been verified.

**Next gate**: obtain permission to retrieve and export specific WebNovel chapters. A future WebNovel chapter fetching adapter needs explicit source authorisation before adding any live download or GitHub Actions smoke test. No full-book workflow is in scope.
