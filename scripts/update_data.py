#!/usr/bin/env python3

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import html
import requests
import yaml

BEST_OF_YAML = "https://raw.githubusercontent.com/tolkonepiu/best-of-mcp-servers/main/projects.yaml"
MCP_HUB_README = "https://raw.githubusercontent.com/apappascs/mcp-servers-hub/main/README.md"  # optional
NO_STARS_SORT_VALUE = 10**12

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_PATH = os.path.join(ROOT_DIR, "data", "servers.json")
SUPPLEMENTAL_PATH = os.path.join(ROOT_DIR, "data", "supplemental_servers.json")
INDEX_PATH = os.path.join(ROOT_DIR, "index.html")
ROBOTS_PATH = os.path.join(ROOT_DIR, "robots.txt")
SITEMAP_PATH = os.path.join(ROOT_DIR, "sitemap.xml")


def http_get(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.text


def gh_headers() -> Dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    h = {
        "accept": "application/vnd.github+json",
        "user-agent": "mcp-radar-update/1.0",
    }
    if token:
        h["authorization"] = f"Bearer {token}"
    return h


CACHE_FILE = os.path.join(ROOT_DIR, "data", "repo_cache.json")


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def gh_repo_meta(github_id: str, cache_ttl_hours: int = 24) -> Dict[str, Any]:
    cache = _load_cache()
    now = datetime.now(timezone.utc).timestamp()

    # check cache
    cached = cache.get(github_id)
    if cached and (now - cached.get("_fetched_at", 0)) < cache_ttl_hours * 3600:
        return cached.get("data", {})
    stale_data = cached.get("data", {}) if cached else {}

    url = f"https://api.github.com/repos/{github_id}"
    max_retries = 3

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=gh_headers(), timeout=60)
        except requests.RequestException as exc:
            if attempt + 1 < max_retries:
                wait = 2 ** (attempt + 2)  # 4, 8 seconds
                print(
                    f"github request failed for {github_id} — retrying in {wait}s "
                    f"(attempt {attempt + 1}/{max_retries}): {exc}",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            print(
                f"gave up on {github_id} after {max_retries} network failures: {exc}",
                file=sys.stderr,
            )
            return stale_data

        rate_limited_403 = r.status_code == 403 and (
            r.headers.get("x-ratelimit-remaining") == "0"
            or bool(r.headers.get("retry-after"))
        )
        if r.status_code in (429, 500, 502, 503, 504) or rate_limited_403:
            if attempt + 1 < max_retries:
                retry_after = r.headers.get("retry-after")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 2)
                print(
                    f"github returned {r.status_code} for {github_id} — retrying in "
                    f"{wait}s (attempt {attempt + 1}/{max_retries})",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            print(
                f"gave up on {github_id} after {max_retries} responses with status "
                f"{r.status_code}",
                file=sys.stderr,
            )
            return stale_data

        # Only definitive absence is safe to cache. Authentication, permission,
        # abuse-detection, and other 4xx failures may be transient.
        if r.status_code in (404, 410):
            cache[github_id] = {"_fetched_at": now, "data": {}}
            _save_cache(cache)
            return {}
        if r.status_code >= 400:
            print(
                f"github returned non-cacheable status {r.status_code} for {github_id}",
                file=sys.stderr,
            )
            return stale_data

        try:
            data = r.json()
            cache[github_id] = {"_fetched_at": now, "data": data}
            _save_cache(cache)
            return data
        except ValueError:
            return stale_data

    return {}


def as_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x if i]
    return [str(x)]


def normalize_url(url: Any) -> str:
    return str(url or "").strip().rstrip("/").lower()


def url_identity_key(url: Any) -> str:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        path = parsed.path.rstrip("/")
        return f"{parsed.netloc}{path}"
    return normalized


def validate_supplemental_url(index: int, raw_url: Any) -> str:
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        raise ValueError(f"supplemental server {index} needs url")
    if any(char.isspace() for char in url):
        raise ValueError(f"supplemental server {index} url must not contain whitespace")

    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"supplemental server {index} url must be an https URL")

    return url


def read_optional_str(item: Dict[str, Any], key: str) -> str:
    return str(item.get(key) or "").strip()


def read_required_str(item: Dict[str, Any], key: str, index: int) -> str:
    value = read_optional_str(item, key)
    if not value:
        raise ValueError(f"supplemental server {index} needs {key}")
    return value


def read_required_list(item: Dict[str, Any], key: str, index: int) -> List[str]:
    values = as_list(item.get(key))
    if not values:
        raise ValueError(f"supplemental server {index} needs {key}")
    return values


def read_optional_int(item: Dict[str, Any], key: str, index: int) -> Optional[int]:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"supplemental server {index} {key} must be an integer")
    return value


def sanitize_supplemental_server(index: int, item: Dict[str, Any]) -> Dict[str, Any]:
    name = read_optional_str(item, "name")
    if not name:
        raise ValueError(f"supplemental server {index} needs name")

    return {
        "name": name,
        "url": validate_supplemental_url(index, item.get("url")),
        "description": read_required_str(item, "description", index),
        "category": read_required_str(item, "category", index),
        "tags": read_required_list(item, "tags", index),
        "stars": read_optional_int(item, "stars", index),
        "last_updated": read_required_str(item, "last_updated", index),
        "source": read_optional_str(item, "source") or "supplemental",
    }


def read_supplemental_servers() -> List[Dict[str, Any]]:
    try:
        with open(SUPPLEMENTAL_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise ValueError("data/supplemental_servers.json must be valid JSON") from exc

    if not isinstance(raw, list):
        raise ValueError("data/supplemental_servers.json must contain a list")

    servers: List[Dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"supplemental server {index} must be an object")
        servers.append(sanitize_supplemental_server(index, item))

    return servers


def supplemental_servers_for_merge() -> List[Dict[str, Any]]:
    try:
        return read_supplemental_servers()
    except ValueError as exc:
        raise ValueError(f"could not load supplemental servers: {exc}") from exc


def site_url_guess() -> str:
    # priority: explicit env
    u = (os.environ.get("SITE_URL") or "").strip()
    if u:
        return u.rstrip("/") + "/"

    # github actions env
    owner = (os.environ.get("GITHUB_REPOSITORY_OWNER") or "").strip()
    repo_full = (os.environ.get("GITHUB_REPOSITORY") or "").strip()  # owner/repo
    repo = repo_full.split("/", 1)[1] if "/" in repo_full else ""

    if owner and repo:
        if repo == f"{owner}.github.io":
            return f"https://{owner}.github.io/"
        return f"https://{owner}.github.io/{repo}/"

    return ""


def write_robots_and_sitemap(generated_at: str, site_url: str) -> None:
    if not site_url:
        return

    robots = "User-agent: *\nAllow: /\n\nSitemap: " + site_url.rstrip("/") + "/sitemap.xml\n"
    with open(ROBOTS_PATH, "w", encoding="utf-8") as f:
        f.write(robots)

    lastmod = generated_at.split("T", 1)[0]
    urls = [
        site_url,
        site_url.rstrip("/") + "/data/servers.json",
    ]

    items = "\n".join(
        [
            "  <url>\n" + f"    <loc>{html.escape(u)}</loc>\n" + f"    <lastmod>{lastmod}</lastmod>\n" + "  </url>"
            for u in urls
        ]
    )

    sitemap = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
        + items
        + "\n</urlset>\n"
    )

    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(sitemap)


def render_prerender_html(servers: List[Dict[str, Any]], limit: int = 120) -> str:
    # simple static html for bots + no-js users
    parts: List[str] = []
    for s in servers[:limit]:
        name = html.escape(str(s.get("name") or "unknown"))
        url = html.escape(str(s.get("url") or "#"))
        desc = html.escape(str(s.get("description") or ""))
        category = html.escape(str(s.get("category") or ""))
        stars = s.get("stars")
        stars_txt = f"stars: {stars}" if isinstance(stars, int) else ""

        badges = " ".join(
            [
                f"<span class=\"badge\">{html.escape(x)}</span>"
                for x in [
                    f"category: {category}" if category else "",
                    stars_txt,
                ]
                if x
            ]
        )

        parts.append(
            "\n".join(
                [
                    '<div class="item">',
                    '  <div class="top">',
                    f'    <a class="name" href="{url}">{name}</a>',
                    '    <span class="badge">prerender</span>',
                    '  </div>',
                    f'  <div class="desc">{desc}</div>',
                    f'  <div class="meta2">{badges}</div>' if badges else '  <div class="meta2"></div>',
                    '</div>',
                ]
            )
        )

    return "\n".join(parts) if parts else '<div class="fine">no data yet.</div>'


def inject_prerender_into_index(prerender_html: str) -> None:
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return

    start = "<!-- prerender:start -->"
    end = "<!-- prerender:end -->"

    if start not in raw or end not in raw:
        return

    before, rest = raw.split(start, 1)
    _, after = rest.split(end, 1)

    new_raw = before + start + "\n" + prerender_html + "\n        " + end + after

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(new_raw)


def main() -> int:
    print("fetching sources…", file=sys.stderr)

    raw_yaml = http_get(BEST_OF_YAML)
    data = yaml.safe_load(raw_yaml)

    projects = data.get("projects") or []
    servers: List[Dict[str, Any]] = []

    # optional: pull the hub readme for future enrichment (not required for mvp)
    try:
        http_get(MCP_HUB_README)
    except Exception:
        pass

    print(f"projects: {len(projects)}", file=sys.stderr)

    for p in projects:
        github_id = (p or {}).get("github_id") or ""
        name = (p or {}).get("name") or github_id
        desc = (p or {}).get("description") or ""
        category = (p or {}).get("category") or ""
        labels = as_list((p or {}).get("labels"))

        if not github_id or "/" not in github_id:
            continue

        meta = gh_repo_meta(github_id)

        stars = meta.get("stargazers_count") if meta else None
        pushed_at = meta.get("pushed_at") if meta else None
        updated_at = meta.get("updated_at") if meta else None

        servers.append(
            {
                "name": name,
                "url": f"https://github.com/{github_id}",
                "description": desc,
                "category": category,
                "tags": labels,
                "stars": stars,
                "last_updated": pushed_at or updated_at,
                "source": "best-of-mcp-servers",
            }
        )

    existing_urls = {url_identity_key(server.get("url")) for server in servers}
    for server in supplemental_servers_for_merge():
        url = url_identity_key(server.get("url"))
        if url and url not in existing_urls:
            servers.append(server)
            existing_urls.add(url)

    def sort_key(s: Dict[str, Any]):
        v = s.get("stars")
        return (-v) if isinstance(v, int) else NO_STARS_SORT_VALUE

    servers.sort(key=sort_key)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    payload = {
        "generated_at": generated_at,
        "count": len(servers),
        "servers": servers,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    prerender_html = render_prerender_html(servers, limit=120)
    inject_prerender_into_index(prerender_html)

    site_url = site_url_guess()
    write_robots_and_sitemap(generated_at, site_url)

    print(f"wrote {OUT_PATH} ({len(servers)} servers)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
