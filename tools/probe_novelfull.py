#!/usr/bin/env python3
"""Live, read-only site-adapter probe: validate two NovelFull chapters in memory.

No chapters, raw HTML, or story text are saved or printed.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
from bs4 import BeautifulSoup
import fanficfare
from fanficfare import adapters
from fanficfare.configurable import Configuration

URL = "https://novelfull.com/interstellar-era-starting-as-a-cleaner.html"


def main() -> int:
    settings = Configuration(adapters.getConfigSectionsFor(URL), "epub")
    settings.read([str(Path(fanficfare.__file__).resolve().parent / "defaults.ini")])
    adapter = adapters.getAdapter(settings, URL)
    adapter.getStoryMetadataOnly(get_cover=False)
    chapters = adapter.chapterInfos
    if len(chapters) < 2:
        raise RuntimeError(f"Expected at least two chapters, found {len(chapters)}")
    print(f"NovelFull live adapter: {len(chapters)} chapters indexed", flush=True)

    digests = set()
    for i in range(2):
        html = adapter.getChapterTextNum(chapters[i]["url"], i)
        soup = BeautifulSoup(html, "html.parser")
        for node in soup.select("script, style"):
            node.decompose()
        text = " ".join(soup.stripped_strings)
        words = text.split()
        if len(words) < 50 or len(text) < 300:
            raise RuntimeError(f"Chapter {i+1} did not yield substantive story text: {len(words)} words")
        low = text.lower()
        if any(w in low[:700] for w in (
            "access denied", "enable javascript", "checking your browser",
            "attention required", "captcha", "just a moment"
        )):
            raise RuntimeError(f"Chapter {i+1} appears to contain an access challenge rather than story text")
        digest = sha256(text.encode("utf-8")).hexdigest()
        if digest in digests:
            raise RuntimeError("Two different chapter URLs returned identical content")
        digests.add(digest)
        print(
            f"LIVE CHAPTER {i+1}/2: text extracted, {len(words)} words, "
            f"{len(text)} characters, sha256={digest[:16]} (no chapter text retained)",
            flush=True,
        )
        del html, soup, text, words

    print("PASS: two distinct NovelFull chapters were retrieved and parsed successfully.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
