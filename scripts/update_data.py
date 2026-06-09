#!/usr/bin/env python3

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import html
import requests
import yaml

BEST_OF_YAML = "https://raw.githubusercontent.com/tolkonepiu/best-of-mcp-servers/main/projects.yaml"
MCP_HUB_README = "https://raw.githubusercontent.com/apappascs/mcp-servers-hub/main/README.md"  # optional

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_PATH = os.path.join(ROOT_DIR, "data", "servers.json")
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

    url = f"https://api.github.com/repos/{github_id}"
    max_retries = 3

    for attempt in range(max_retries):
        r = requests.get(url, headers=gh_headers(), timeout=60)

        if r.status_code == 429:
            wait = 2 ** (attempt + 2)  # 4, 8, 16 seconds
            print(f"rate limited — retrying in {wait}s (attempt {attempt + 1}/{max_retries})", file=sys.stderr)
            import time
            time.sleep(wait)
            continue

        # handle renamed/deleted repos gracefully
        if r.status_code >= 400:
            cache[github_id] = {"_fetched_at": now, "data": {}}
            _save_cache(cache)
            return {}

        try:
            data = r.json()
            cache[github_id] = {"_fetched_at": now, "data": data}
            _save_cache(cache)
            return data
        except Exception:
            return {}

    print(f"gave up on {github_id} after {max_retries} retries due to rate limiting", file=sys.stderr)
    return {}


def as_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x if i]
    return [str(x)]


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

    def sort_key(s: Dict[str, Any]):
        v = s.get("stars")
        return (-v) if isinstance(v, int) else (10**12)

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
