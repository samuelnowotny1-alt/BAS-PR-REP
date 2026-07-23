#!/usr/bin/env python3
"""Probe release routes and internal links using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.cookiejar import CookieJar
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urldefrag, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, OpenerDirector, Request, build_opener


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


def fetch(opener: OpenerDirector, url: str) -> tuple[int, bytes, str, str]:
    parts = urlsplit(url)
    encoded_url = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            quote(parts.path, safe="/%:@"),
            quote(parts.query, safe="=&%:+,"),
            parts.fragment,
        )
    )
    request = Request(encoded_url, headers={"User-Agent": "bas-assistant-release-smoke/1.0"})
    try:
        with opener.open(request, timeout=15) as response:
            return response.status, response.read(), response.headers.get("Content-Type", ""), response.geturl()
    except HTTPError as error:
        return error.code, error.read(), error.headers.get("Content-Type", ""), error.geturl()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--username-env", default="BAS_SMOKE_USERNAME")
    parser.add_argument("--password-env", default="BAS_SMOKE_PASSWORD")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/") + "/"
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    username = os.environ.get(args.username_env, "")
    password = os.environ.get(args.password_env, "")
    if username and password:
        login_request = Request(
            urljoin(base_url, "login"),
            data=urlencode({"username": username, "password": password}).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "bas-assistant-release-smoke/1.0",
            },
        )
        with opener.open(login_request, timeout=15) as response:
            if urlparse(response.geturl()).path == "/login":
                print("FAIL authentication did not leave the login page", file=sys.stderr)
                return 1
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
            status, body, content_type, final_url = fetch(opener, url)
        except URLError as error:
            failures.append(f"{url}: {error.reason}")
            continue
        final_path = urlparse(final_url).path
        redirect_note = f" -> {final_path}" if final_url != url else ""
        print(f"{status} {url}{redirect_note}")
        if status >= 400:
            failures.append(f"{url}: HTTP {status}")
        elif route not in {"", "healthz"} and final_path == "/login":
            failures.append(f"{url}: redirected to login; provide smoke credentials")
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
                status, _, _, final_url = fetch(opener, link)
            except URLError as error:
                failures.append(f"{link}: {error.reason}")
                continue
            if status >= 400:
                failures.append(f"{link}: HTTP {status} (linked from {page_url})")
            elif urlparse(final_url).path == "/login" and urlparse(link).path != "/login":
                failures.append(f"{link}: redirected to login (linked from {page_url})")

    print(f"Checked {len(routes)} release routes and {len(checked)} rendered links.")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("Release smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
