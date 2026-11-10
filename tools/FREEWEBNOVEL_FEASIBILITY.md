# FreeWebNovel: two-chapter compatibility check

FreeWebNovel is **not** an adapter in the project's existing FanFicFare
dependency. Do not use the existing NovelFull Actions on freewebnovel.com
links. The NovelFull workflow calls FanFicFare, which will reject unknown
sites; changing only the URL is insufficient.

The site publishes ordinary novel index URLs such as:

- Book: https://freewebnovel.com/novel/the-first-order
- Chapter 1: https://freewebnovel.com/novel/the-first-order/chapter-1
- Chapter 2: https://freewebnovel.com/novel/the-first-order/chapter-2

The catalogue currently shows the first 40 chapters and additional chapter
ranges through a pagination control. The full-book chapter index is NOT yet
implemented, and must not be assumed to fit in the first catalogue response.
Another site's adapter, described in a public GitHub discussion, suggests
that readable chapter text may be present in a .txt element. This has not
been confirmed by a live request from this repository.

## Windows test

In PowerShell, from the Novel_Library repository root:

~~~powershell
git pull
python -m pip install -r requirements.txt

python -m tools.freewebnovel_probe "https://freewebnovel.com/novel/the-first-order" --catalog-only

python -m tools.freewebnovel_probe "https://freewebnovel.com/novel/the-first-order" --confirm-rights
~~~

The first command loads **only the public book catalogue**, shows the title
and discovered public Chapter 1 and 2 links. The second makes **at most
three page requests in total**: the catalogue followed by Chapter 1 and
Chapter 2, with a one-second pause between the chapter requests.

No copyrighted chapter prose is printed, written to files or uploaded to
GitHub. The result reports chapter text length, paragraph count, selector,
and short SHA-256 fingerprint to assess extraction. A successful check does
**not** imply permission to archive a full book. Use only where you have
the appropriate authorisation, and respect site access restrictions.

If the page uses Cloudflare challenges, redirects, authentication, locked
chapters or unexpected HTML, the probe **stops immediately**. No retries,
browser-cache access, cookie import, proxy rotation or access-control bypass
are attempted.

## Scope and next milestone

Do not add a one-off test workflow to the Actions menu. The shared CI
workflow runs synthetic unit tests without contacting FreeWebNovel.

If the user's ordinary Windows connection can read Chapters 1 and 2,
the next task is a **separate** FreeWebNovel downloader and Actions:
- \`FreeWebNovel - Download\`
- \`FreeWebNovel - Bulk Download\`

Reuse the project's existing novel identity, registry, chapter TXT/EPUB
packaging and ZIP artifact conventions; keep NovelFull and WebNovel adapters
intact. Before that, verify catalogue pagination, title/author metadata,
chapter text completeness, access rights and supported full-book retrieval.
