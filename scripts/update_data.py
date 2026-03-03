#!/usr/bin/env python3

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import yaml

BEST_OF_YAML = "https://raw.githubusercontent.com/tolkonepiu/best-of-mcp-servers/main/projects.yaml"
MCP_HUB_README = "https://raw.githubusercontent.com/apappascs/mcp-servers-hub/main/README.md"  # optional

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "servers.json")


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


def gh_repo_meta(github_id: str) -> Dict[str, Any]:
    url = f"https://api.github.com/repos/{github_id}"
    r = requests.get(url, headers=gh_headers(), timeout=60)

    # handle renamed/deleted repos gracefully
    if r.status_code >= 400:
        return {}

    try:
        return r.json()
    except Exception:
        return {}


def as_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x if i]
    return [str(x)]


def main() -> int:
    print("fetching sources…", file=sys.stderr)

    raw_yaml = http_get(BEST_OF_YAML)
    data = yaml.safe_load(raw_yaml)

    projects = data.get("projects") or []
    servers: List[Dict[str, Any]] = []

    # optional: pull the hub readme for future enrichment (not required for mvp)
    _ = None
    try:
        _ = http_get(MCP_HUB_README)
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

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(servers),
        "servers": servers,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"wrote {OUT_PATH} ({len(servers)} servers)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
