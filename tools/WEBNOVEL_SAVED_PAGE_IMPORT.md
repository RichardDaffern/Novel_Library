# Import authorised WebNovel chapters saved locally

This is the **network-free fallback** when WebNovel's site rejects scripted requests.
The existing NovelFull downloader and workflows are entirely unchanged.
This importer handles **one or two** chapters, not full novels.

## Saving the source files

If you have permission to export the chapter text, open each free chapter in your
normal browser and use its ordinary **Save Page As** feature (HTML format).
Alternatively, save your permitted chapter text as individual UTF-8 `.txt` files.

Do not save or export premium/locked chapters or attempt to circumvent a site's
access controls. This importer does not use cookies, login credentials, or the
WebNovel website.

Some browser-saved HTML pages do not contain the readable chapter body. In that
case the tool **fails closed** rather than exporting navigation or empty text.
If you are authorised to do so, supplying the readable chapter text as a local
`.txt` file is the alternative.

## Convert the first two chapters on Windows

Install the existing requirements once: `python -m pip install -r requirements.txt`.

From the project directory in PowerShell:

```powershell
python -m tools.webnovel_saved_pages --book-title "My Example Story" --author "Example Author" --chapter-1 "chapter1.html" --chapter-1-title "Chapter 1: First Day" --chapter-2 "chapter2.html" --chapter-2-title "Chapter 2: Second Day" --output-dir "webnovel-local-test" --confirm-rights
```

The output directory must be new or empty. Output files are:
- `chapter-01.txt` and `chapter-02.txt`
- `book.txt`
- `book.epub`
- `metadata.json`

You can omit the second-chapter arguments for a one-chapter check.
Use `--confirm-rights` only for material you have permission to export.

The importer does **not** automatically retrieve chapters from WebNovel URLs.
Live URL retrieval remains blocked by WebNovel's Cloudflare challenge. Passing
offline tests does not establish that a particular browser-saved page includes
the text or that an individual book grants export permission.

## Offline tests

```powershell
python -m unittest tests.test_webnovel_saved_pages -v
```

Linux and Windows repository CI discover these tests. Test fixtures are original
fictional prose and no copyrighted WebNovel chapters are uploaded into Git.
