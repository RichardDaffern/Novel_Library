#!/usr/bin/env python3
"""Single-request HTTP status diagnosis for WebNovel public book pages.

Does not fetch chapter text, bypass access controls, inspect cookies or save
response bodies. Use the same default User-Agent as the existing public probe.
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tools.webnovel_probe import validate_book_url

AGENT = "NovelLibraryPublicFeasibility/0.1"
ALLOWED_HEADERS = (
    "content-type", "server", "retry-after", "www-authenticate",
    "x-cache", "via", "cf-ray", "cf-mitigated", "x-amz-cf-id",
)


def _safe_headers(headers):
    result = {}
    for key in ALLOWED_HEADERS:
        value = headers.get(key)
        if value:
            # No cookies, session tokens, full URLs or sensitive headers.
            result[key] = str(value).strip()[:160]
    return result


def diagnose(url, opener=urlopen):
    url = validate_book_url(url)
    request = Request(url, headers={"User-Agent": AGENT})
    try:
        with opener(request, timeout=12) as response:
            return {
                "status": response.status,
                "redirected": response.geturl() != url,
                "headers": _safe_headers(response.headers),
                "diagnosis": "success; public book HTML was not saved",
            }
    except HTTPError as exc:
        result = {
            "status": exc.code,
            "headers": _safe_headers(exc.headers),
            "diagnosis": "access refused; no further request attempted" if exc.code == 403
                         else "HTTP error; no further request attempted",
        }
        exc.close()
        return result
    except (URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
        # Avoid printing low-level error strings that might include a proxy URL.
        return {"status": None, "diagnosis": "network or TLS connection error",
                "error_type": type(exc).__name__}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book_url")
    args = parser.parse_args(argv)
    try:
        result = diagnose(args.book_url)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, indent=2))
    # 403 is a diagnosed response, not a software crash.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
