#!/usr/bin/env python3
"""Run FanFicFare CLI while reporting chapter counts and percentages.

FanFicFare's --progressbar outputs a dot per network fetch, not per chapter.
This wrapper uses FanFicFare's chapter-completion notification callback.
"""

from __future__ import annotations

import sys
from pathlib import Path
from bs4 import BeautifulSoup


def _checkpoint_chapter(folder: Path, index: int, title: str, html: str | bytes) -> Path:
    """Save a successfully fetched chapter before EPUB creation."""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.select("script, style"):
        el.decompose()
    lines = [p.get_text(" ", strip=True) for p in soup.find_all(("p", "blockquote", "pre", "li"))]
    lines = [p for p in lines if p]
    body = "\n\n".join(lines) if lines else soup.get_text("\n", strip=True)
    if not body.strip():
        raise ValueError(f"Downloaded chapter {index+1} was empty")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"chapter_{index+1:05d}.txt"
    temporary = destination.with_suffix(".txt.tmp")
    temporary.write_text(f"{title}\n\n{body.strip()}\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def progress_reporter(writer):
    """Return a callback reporting progress for the selected chapter range."""
    adapter = writer.adapter
    count = len(adapter.chapterInfos)
    first = adapter.chapterFirst if adapter.chapterFirst is not None else 0
    last = adapter.chapterLast if adapter.chapterLast is not None else count - 1
    first = max(0, first)
    last = min(count - 1, last)
    total = max(0, last - first + 1)
    completed = 0
    print(f"Chapter range: {total} selected of {count} chapters", flush=True)

    # Chapter content is saved as soon as FanFicFare returns it.
    # This runs before the EPUB is written, so an interrupted job leaves files.
    if hasattr(adapter, "getChapterTextNum"):
        original_fetch = adapter.getChapterTextNum
        checkpoint_dir = Path.cwd() / "chapters_in_progress"
        def checkpointing_fetch(url, index):
            html = original_fetch(url, index)
            if first <= index <= last:
                heading = adapter.chapterInfos[index].get("title", f"Chapter {index+1}")
                file = _checkpoint_chapter(checkpoint_dir, index, heading, html)
                print(f"Saved checkpoint: {file.name}", flush=True)
            return html
        adapter.getChapterTextNum = checkpointing_fetch

    def notify(_fraction, _url):
        nonlocal completed
        completed += 1
        if total:
            print(f"Chapters processed: {completed}/{total} ({100 * completed / total:.1f}%)", flush=True)

    return notify


def main(argv: list[str] | None = None):
    """Delegate site access, configuration and EPUB creation to FanFicFare."""
    from fanficfare import cli
    from fanficfare.writers.base_writer import BaseStoryWriter

    original = BaseStoryWriter.writeStory

    def patched(self, *args, **kwargs):
        if not kwargs.get("metaonly", False) and "notification" not in kwargs and len(args) < 5:
            kwargs["notification"] = progress_reporter(self)
        return original(self, *args, **kwargs)

    BaseStoryWriter.writeStory = patched
    try:
        cli.main(argv if argv is not None else sys.argv[1:])
    finally:
        BaseStoryWriter.writeStory = original


if __name__ == "__main__":
    main()
