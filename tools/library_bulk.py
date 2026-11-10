#!/usr/bin/env python3
"""Plan selected novels across NovelFull and FreeWebNovel by saved titles or URLs.

GitHub's manual workflow has no dynamic multi-select input. Accept a
comma/semicolon/newline-separated name list and a static website choice.
Names are resolved only from the verified registry or explicitly curated
sources; unknown and ambiguous names fail instead of guessing URLs.
"""
from __future__ import annotations

import argparse
from difflib import get_close_matches
import json
import os
from pathlib import Path
import re

from tools.bulk_download import MAX_NOVELS, parse_novel_urls
from tools.download_registry import (
    already_available, canonical_url, normalise_range, read_registry,
    website_name,
)
from tools.freewebnovel_probe import validate_book_url

SITES = ("NovelFull", "FreeWebNovel")
WEBSITE_CHOICES = ("All",) + SITES
DEFAULT_CATALOGUE = Path("novel_sources.json")


def _normal_name(text: str) -> str:
    return " ".join(text.split()).casefold()


def _validated_url(value: str) -> tuple[str, str]:
    url = canonical_url(value)
    site = website_name(url)
    if site == "FreeWebNovel":
        return site, validate_book_url(url)
    if site == "NovelFull":
        # Prevent accidental use of unsupported websites/novel pages.
        if not re.fullmatch(r"/[a-z0-9_-]+\.html", __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).path):
            raise ValueError("NovelFull URLs must point to /novel-name.html")
        if __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).query:
            raise ValueError("NovelFull URL must not include query parameters")
        return site, url
    raise ValueError(f"Unsupported website: {site}. Supported: {', '.join(SITES)}")


def catalogue_entries(registry: dict, curated: dict) -> list[dict]:
    entries = []
    for record in list(registry.get("novels", [])) + list(curated.get("novels", [])):
        title, url = record.get("title"), record.get("url")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Catalogue novel has no title")
        site, url = _validated_url(url)
        entries.append({"title": title.strip(), "url": url, "site": site})
    return entries


def read_curated(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "novels": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("novels"), list):
        raise ValueError("Invalid novel_sources.json format")
    return data


def parse_names(raw: str, names: list[str]) -> list[str]:
    """Allow comma lists, plus semicolon/newline for titles containing commas."""
    known = {_normal_name(name) for name in names}
    parts = []
    for segment in re.split(r"[;\r\n]+", raw or ""):
        segment = segment.strip()
        if not segment:
            continue
        if _normal_name(segment) in known:
            parts.append(segment)
        else:
            parts.extend(part.strip() for part in segment.split(",") if part.strip())
    return parts


def selection_plan(
    registry: dict, curated: dict, names: str, urls: str, website: str = "All",
    chapter_range: str = "", force: bool = False,
) -> dict:
    if website not in WEBSITE_CHOICES:
        raise ValueError(f"Website must be one of: {', '.join(WEBSITE_CHOICES)}")
    entries = catalogue_entries(registry, curated)
    requested_names = parse_names(names, [e["title"] for e in entries])
    requested_urls = parse_novel_urls(urls) if urls.strip() else []
    if not requested_names and not requested_urls:
        raise ValueError("Choose at least one novel name or paste at least one novel URL")
    chosen: dict[str, dict] = {}
    for name in requested_names:
        candidates = [
            item for item in entries
            if _normal_name(item["title"]) == _normal_name(name)
            and (website == "All" or item["site"] == website)
        ]
        unique = {item["url"]: item for item in candidates}
        if not unique:
            available = sorted({
                item["title"] for item in entries
                if website == "All" or item["site"] == website
            })
            near = get_close_matches(name, available, n=3, cutoff=0.5)
            suffix = f" Possible matches: {', '.join(near)}." if near else ""
            raise ValueError(
                f"Unknown novel name {name!r} for {website}. "
                f"Add it to novel_sources.json or paste its exact URL.{suffix}"
            )
        if len(unique) > 1:
            raise ValueError(
                f"Ambiguous novel name {name!r} matches multiple URLs. "
                "Choose a specific website or use the novel's URL."
            )
        item = next(iter(unique.values()))
        chosen[item["url"]] = item
    for raw in requested_urls:
        site, url = _validated_url(raw)
        if website != "All" and website != site:
            raise ValueError(
                f"URL {url} is from {site}, but website filter is {website}"
            )
        item = next((entry for entry in entries if entry["url"] == url), None)
        chosen[url] = item or {"url": url, "title": url.rsplit("/", 1)[-1], "site": site}
    if len(chosen) > MAX_NOVELS:
        raise ValueError(f"Maximum {MAX_NOVELS} distinct novels per bulk run")
    rng = normalise_range(chapter_range)
    groups = {site: [] for site in SITES}
    skipped = []
    for item in sorted(chosen.values(), key=lambda i: (i["site"], i["title"].casefold(), i["url"])):
        payload = {
            "novel_url": item["url"],
            "chapter_range": "" if rng == "all" else rng,
            "force": bool(force),
            "title": item["title"],
        }
        if not force and already_available(registry, item["url"], rng):
            skipped.append({"site": item["site"], **payload})
        else:
            groups[item["site"]].append(payload)
    return {
        "version": 1, "website": website, "range": rng,
        "groups": groups, "skipped": skipped,
        "selected_count": len(chosen),
    }


def _output(key: str, value: str) -> None:
    file = os.environ.get("GITHUB_OUTPUT")
    if file:
        with open(file, "a", encoding="utf-8") as handle:
            handle.write(f"{key}={value}\n")


def write_actions(plan: dict) -> None:
    for site, prefix in (("NovelFull", "novelfull"), ("FreeWebNovel", "freewebnovel")):
        group = plan["groups"][site]
        _output(f"has_{prefix}", "true" if group else "false")
        _output(f"{prefix}_matrix", json.dumps({
            "include": [
                {k: row[k] for k in ("novel_url", "chapter_range", "force")}
                for row in group
            ]
        }, separators=(",", ":")))
    messages = [
        "## Library bulk download",
        "",
        f"Selected: {plan['selected_count']}; skipped (artifact available): {len(plan['skipped'])}.",
    ]
    for site in SITES:
        lines = plan["groups"][site]
        messages.extend(["", f"### {site} ({len(lines)} to download)"])
        messages.extend(f"- {item['title']} ({item['chapter_range'] or 'all'})" for item in lines)
    if plan["skipped"]:
        messages.extend(["", "### Already available"])
        messages.extend(f"- {item['site']}: {item['title']}" for item in plan["skipped"])
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(messages) + "\n")
    print("\n".join(messages))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "list"))
    parser.add_argument("--names", default="", help="Comma, semicolon or newline separated saved novel names")
    parser.add_argument("--urls", default="", help="Optional new novel URLs")
    parser.add_argument("--website", default="All", choices=WEBSITE_CHOICES)
    parser.add_argument("--chapter-range", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--registry", type=Path, default=Path("downloaded_novels.json"))
    parser.add_argument("--catalogue", type=Path, default=DEFAULT_CATALOGUE)
    parser.add_argument("--plan-file", type=Path, default=Path("library_bulk_plan.json"))
    args = parser.parse_args(argv)
    try:
        registry = read_registry(args.registry)
        curated = read_curated(args.catalogue)
        if args.action == "list":
            for site in SITES:
                print(f"\n{site}")
                unique = sorted({e["title"] for e in catalogue_entries(registry, curated)
                                 if e["site"] == site}, key=str.casefold)
                print("\n".join(f"- {title}" for title in unique) or "(no saved novels)")
            return 0
        plan = selection_plan(registry, curated, args.names, args.urls,
                              args.website, args.chapter_range, args.force)
        args.plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        write_actions(plan)
        return 0
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
