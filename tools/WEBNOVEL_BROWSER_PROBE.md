# WebNovel: automatic retrieval feasibility test (normal browser)

## Why this exists

A direct HTTP request from Python and GitHub Actions gets WebNovel's Cloudflare
403 challenge. The **offline saved-page import** works, but requires each
chapter to be saved manually.

This independent probe tests whether a **standard, unmodified Chromium**
browser can load the public book catalogue and **two freely readable chapter
pages** without the site refusing access. It uses no cookies from an existing
browser profile, login credentials, stealth modifications, proxies, challenge
solvers, paywall handling, or anti-bot bypasses.

**It is not yet an all-chapter downloader.** Only the first two publicly linked
chapters are attempted, and no other chapter text is fetched. If the site
blocks normal browser automation, the tool stops and reports the reason.
Do not repeatedly retry denied requests.

## Windows setup

From the repository directory in PowerShell:

~~~powershell
git pull
python -m pip install -r requirements.txt
python -m pip install playwright
python -m playwright install chromium
~~~

The Playwright package is optional; existing NovelFull and local import commands
do not require it.

## Test the public book

Use a **fresh, empty** output directory for this test:

~~~powershell
python -m tools.webnovel_browser_probe "https://www.webnovel.com/book/33422293300201205" `
  --book-title "Harry Potter: Platinum Dragon Wizard" `
  --author "BlurryPinkSnake" `
  --output-dir "webnovel-browser-test" `
  --confirm-rights
~~~

By default a regular visible Chromium window opens. The browser will request
the book page and inspect its initial HTML. If Chapters 1 and 2 are not found,
it will **click the visible "Table of Contents" tab**, which your November 9
screen recording showed beside "About", and wait briefly for the chapter
links to render. It selects the actual Chapter 1 and Chapter 2 by their
visible labels, ignoring the "Latest Release" link near the top. The link
shape shown in your video is /book/<book-id>/<chapter-id>.

Only the first two public chapter pages will then be visited. If the site
serves an access challenge, redirects the browser, or does not expose
readable chapter text, no export is performed.

If chapter links are not present in the book page's rendered HTML, you can
supply both publicly visible links copied from the site's chapter navigation
using --chapter-1-url and --chapter-2-url. This does **not** authorise private
endpoints or unlock locked content. Avoid copying session tokens into URLs.

If successful, output includes chapter-01.txt, chapter-02.txt, book.txt,
book.epub and metadata.json. Do not upload story text to GitHub.

## What success and failure mean

- **Success:** We have confirmed a normal browser can read these two public
  pages on the device running the test. After checking the resulting EPUB,
  we can build resumable chapter-range downloading on the same supported path.
- **Confirmed Cloudflare challenge:** The probe checks Cloudflare's documented
  `cf-mitigated: challenge` response header and recognises actual challenge
  page titles or verification-only pages. It stops immediately without trying
  to solve or bypass a challenge.
- **HTTP 403:** Browser-based unattended retrieval is refused in this
  environment. We will not implement evasion of that restriction.
- **HTML contains Cloudflare script names:** Unlike the original probe, the
  updated detector does not assume that a page is blocked merely because a
  site's HTML includes challenge-related JavaScript. Only a true challenge
  signal blocks retrieval.
- **Chapter links absent:** The book catalogue may use an interactive or
  changed layout. Provide the two normal chapter URLs to separate chapter-link
  discovery from the access check.
- **Locked/unknown layout:** No content is exported. This tool never guesses
  hidden chapter text.

We have not established that every chapter of any specific novel is free,
export-authorised, or accessible to automation. Users must have appropriate
rights for content they export. WebNovel's own offline downloading option is
a separate feature in its official mobile app and does not automatically
provide an EPUB for this project.

## Safe offline tests

~~~powershell
python -m unittest tests.test_webnovel_browser_probe -v
~~~

CI uses a synthetic browser object and original test prose. CI never makes
WebNovel chapter requests and never attempts to beat Cloudflare.
