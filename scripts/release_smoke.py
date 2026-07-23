#!/usr/bin/env python3
"""Probe release routes and internal links using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attribute = "href" if tag in {"a", "link"} else "src" if tag in {"img", "script"} else None
        if attribute is None:
            return
        value = dict(attrs).get(attribute)
        if value:
            self.links.add(value)


def fetch(url: str) -> tuple[int, bytes, str]:
    request = Request(url, headers={"User-Agent": "bas-assistant-release-smoke/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except HTTPError as error:
        return error.code, error.read(), error.headers.get("Content-Type", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/") + "/"
    project_root = f"project/{args.project_id}"
    routes = [
        "",
        "healthz",
        project_root,
        f"{project_root}/documents",
        f"{project_root}/validate",
        f"{project_root}/graphics",
        f"{project_root}/logic",
        f"{project_root}/export",
        f"{project_root}/import",
    ]
    failures: list[str] = []
    pages: list[tuple[str, bytes]] = []

    for route in routes:
        url = urljoin(base_url, route)
        try:
            status, body, content_type = fetch(url)
        except URLError as error:
            failures.append(f"{url}: {error.reason}")
            continue
        print(f"{status} {url}")
        if status >= 400:
            failures.append(f"{url}: HTTP {status}")
        elif "text/html" in content_type:
            pages.append((url, body))
        elif route == "healthz":
            payload = json.loads(body)
            if payload.get("status") != "ok":
                failures.append(f"{url}: unhealthy response")

    checked: set[str] = set()
    for page_url, body in pages:
        link_parser = LinkParser()
        link_parser.feed(body.decode("utf-8", errors="replace"))
        for raw_link in link_parser.links:
            if raw_link.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                continue
            link = urldefrag(urljoin(page_url, raw_link)).url
            parsed = urlparse(link)
            if parsed.netloc != urlparse(base_url).netloc or link in checked:
                continue
            if parsed.path.startswith("/api/") or parsed.path.endswith((".csv", ".json", ".zip")):
                continue
            checked.add(link)
            try:
                status, _, _ = fetch(link)
            except URLError as error:
                failures.append(f"{link}: {error.reason}")
                continue
            if status >= 400:
                failures.append(f"{link}: HTTP {status} (linked from {page_url})")

    print(f"Checked {len(routes)} release routes and {len(checked)} rendered links.")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("Release smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
