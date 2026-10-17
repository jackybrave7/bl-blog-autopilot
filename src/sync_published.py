"""Sync data/published.json from existing WordPress posts (source links)."""

from __future__ import annotations

import argparse
import json
import re

import requests

from src.lib import PUBLISHED_FILE, load_published, save_published, wp_config

SOURCE_LINK_RE = re.compile(
    r'Источник:\s*<a\s+href="([^"]+)"',
    re.IGNORECASE,
)

# WP API times out on large pages; cap recent posts only (never shrink published.json).
PER_PAGE = 5
MAX_PUBLISH_PAGES = 30
MAX_DRAFT_PAGES = 15
REQUEST_TIMEOUT = (10, 90)


def extract_source_url(content: str | dict) -> str | None:
    if isinstance(content, dict):
        text = content.get("raw") or content.get("rendered") or ""
    else:
        text = content
    match = SOURCE_LINK_RE.search(text)
    return match.group(1).strip() if match else None


def _fetch_posts(
    base: str,
    auth: tuple[str, str],
    *,
    status: str,
    max_pages: int,
) -> list[dict]:
    posts: list[dict] = []
    for page in range(1, max_pages + 1):
        resp = requests.get(
            f"{base}/wp-json/wp/v2/posts",
            params={
                "per_page": PER_PAGE,
                "page": page,
                "status": status,
                "_fields": "id,title,status,content",
            },
            auth=auth,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return posts


def _merge_post(
    post: dict,
    by_url: dict[str, dict],
    added: list[dict],
    refreshed: list[dict],
) -> None:
    source_url = extract_source_url(post["content"])
    if not source_url:
        return
    entry = {
        "source_url": source_url,
        "wp_post_id": post["id"],
        "title": post["title"]["rendered"] if isinstance(post["title"], dict) else post["title"],
        "status": post["status"],
    }
    prev = by_url.get(source_url)
    if not prev:
        by_url[source_url] = entry
        added.append(entry)
        return
    if prev.get("wp_post_id") != post["id"] or prev.get("title") != entry["title"]:
        # Prefer published post if the same source appears twice.
        if prev.get("status") == "publish" and entry["status"] != "publish":
            return
        if entry["status"] == "publish" and prev.get("status") != "publish":
            by_url[source_url] = entry
            refreshed.append(entry)
        elif prev.get("wp_post_id") != post["id"]:
            by_url[source_url] = entry
            refreshed.append(entry)


def sync_published_from_wp(*, dry_run: bool = False) -> dict:
    """Merge WP posts with «Источник» links into published.json."""
    wp = wp_config()
    auth = (wp["user"], wp["password"])
    base = wp["url"]

    by_url: dict[str, dict] = {
        e["source_url"]: dict(e) for e in load_published() if e.get("source_url")
    }
    added: list[dict] = []
    refreshed: list[dict] = []

    for status, max_pages in (("publish", MAX_PUBLISH_PAGES), ("draft", MAX_DRAFT_PAGES)):
        for post in _fetch_posts(base, auth, status=status, max_pages=max_pages):
            _merge_post(post, by_url, added, refreshed)

    entries = list(by_url.values())
    if not dry_run:
        save_published(entries)

    return {
        "total": len(entries),
        "added": len(added),
        "refreshed": len(refreshed),
        "added_posts": added,
        "refreshed_posts": refreshed,
        "file": str(PUBLISHED_FILE),
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync published.json from WordPress")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = sync_published_from_wp(dry_run=args.dry_run)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
