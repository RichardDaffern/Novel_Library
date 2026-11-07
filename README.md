# Novel Library

FanFicFare-based local downloader and EPUB chapter exporter. **Only download and store works where you have permission and the site permits automated access.** This project does not circumvent access controls. Downloaded books are not committed to Git.

## Install (Python 3.12)

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Run a complete offline, nine-chapter synthetic test:

```powershell
python -u novel_downloader.py --self-test
```

Test an inclusive three-chapter range, without contacting any website:

```powershell
python -u novel_downloader.py --self-test --chapter-range 3-5
```

For an authorised novel URL:

```powershell
python -u novel_downloader.py "https://example.com/novel" --confirm-rights --chapter-range 1-30
python -u novel_downloader.py "https://example.com/novel" --confirm-rights --chapter-range 31-60
```

Chapter positions are **1-based and inclusive** in the FanFicFare chapter index, including prologues. The standalone `--begin-chapter` and `--end-chapter` flags remain supported. Each range has a separate EPUB and folder, avoiding accidental reuse of a previous range.

## Where individual chapter files go

While the downloader is running, each fetched chapter is saved immediately under `downloads/<novel-name>/chapters_in_progress/chapter_00001.txt`. The console prints `Saved checkpoint` and `Chapters processed: 3/30 (10.0%)`. Chapter percentages count completed chapters, not HTTP requests. Chapter-index discovery happens before chapter downloading and may itself take time.

After a successful EPUB export, the folder contains `source.epub`, `metadata.json`, `chapters.json`, and numbered `chapter_*.txt` files. The temporary checkpoints are then removed. On errors, checkpoints remain in the folder; automatic mid-run resume is **not** implemented.

The `chapters.json` manifest records chapter-index positions, headings, filenames, word counts and checksums. Output folders for ranges include both boundaries, e.g. `novel-chapters-0001-0030`.

## GitHub Actions

The **Test novel library** workflow runs unit tests and a complete synthetic FanFicFare download on Linux and Windows, plus a short public-domain EPUB import. It tests the range `3-5` and uploads the **verified-test-books** artifact (synthetic and public-domain test files only). A NovelFull index-only compatibility check for *Interstellar Era: Starting as a Cleaner* is nonblocking and downloads no story text.

The **Download permitted novel** workflow is manually triggered. Supply the URL, acknowledge that you have archive rights, and optionally enter a single range such as `1-30`. This workflow refuses to run on a **public repository**, to avoid exposing private archives through downloadable GitHub artifacts. Change the repository to private before using it. GitHub Actions artifacts are downloadable only after a workflow run finishes; they are not live files on your laptop.

## Offline EPUB imports

```powershell
python novel_downloader.py --import-epub "C:\\Books\\book.epub"
```

For download permissions, see the source website's terms and the author's licence.
