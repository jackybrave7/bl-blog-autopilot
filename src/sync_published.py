"""Sync data/published.json from existing WordPress posts (source links)."""

from __future__ import annotations

import argparse
import json
import re

import requests

from src.lib import PUBLISHED_FILE, load_published, save_published, wp_config

SESSION = requests.Session()
SOURCE_LINK_RE = re.compile(
    r'Источник:\s*<a\s+href="([^"]+)"',
    re.IGNORECASE,
)
WP_SYNC_PER_PAGE = 5
WP_SYNC_TIMEOUT = 30
WP_SYNC_RETRIES = 3


def extract_source_url(content: str) -> str | None:
    match = SOURCE_LINK_RE.search(content)
    return match.group(1).strip() if match else None


def _fetch_posts_page(
    base: str,
    auth: tuple[str, str],
    *,
    status: str,
    page: int,
) -> list[dict]:
    last_error: Exception | None = None
    for attempt in range(1, WP_SYNC_RETRIES + 1):
        try:
            resp = SESSION.get(
                f"{base}/wp-json/wp/v2/posts",
                params={
                    "per_page": WP_SYNC_PER_PAGE,
                    "page": page,
                    "status": status,
                    "_fields": "id,title,status,content",
                },
                auth=auth,
                timeout=WP_SYNC_TIMEOUT,
            )
            if resp.status_code == 400:
                return []
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < WP_SYNC_RETRIES:
                continue
            raise last_error from exc
    return []


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

    for status in ("publish", "draft"):
        page = 1
        while True:
            posts = _fetch_posts_page(base, auth, status=status, page=page)
            if not posts:
                break

            for post in posts:
                content = post.get("content", {})
                raw_html = content.get("raw") or content.get("rendered") or ""
                source_url = extract_source_url(raw_html)
                if not source_url:
                    continue
                title = post.get("title", {})
                entry = {
                    "source_url": source_url,
                    "wp_post_id": post["id"],
                    "title": title.get("raw") or title.get("rendered") or "",
                    "status": post["status"],
                }
                prev = by_url.get(source_url)
                if not prev:
                    by_url[source_url] = entry
                    added.append(entry)
                    continue
                if prev.get("wp_post_id") != post["id"] or prev.get("title") != entry["title"]:
                    # Prefer published post if the same source appears twice.
                    if prev.get("status") == "publish" and entry["status"] != "publish":
                        continue
                    if entry["status"] == "publish" and prev.get("status") != "publish":
                        by_url[source_url] = entry
                        refreshed.append(entry)
                    elif prev.get("wp_post_id") != post["id"]:
                        by_url[source_url] = entry
                        refreshed.append(entry)

            page += 1

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
