"""Sync data/published.json from existing WordPress posts (source links)."""

from __future__ import annotations

import argparse
import json
import re
import time

import requests

from src.lib import PUBLISHED_FILE, load_published, save_published, wp_config

SESSION = requests.Session()
SOURCE_LINK_RE = re.compile(
    r'Источник:\s*<a\s+href="([^"]+)"',
    re.IGNORECASE,
)
LIST_PAGE_SIZE = 20
CONTENT_TIMEOUT = 90


def extract_source_url(content: str) -> str | None:
    match = SOURCE_LINK_RE.search(content)
    return match.group(1).strip() if match else None


def fetch_post_summaries(base: str, auth: tuple[str, str], page: int) -> list | None:
    """List recent posts without body (fast). Returns None when pagination ends."""
    resp = SESSION.get(
        f"{base}/wp-json/wp/v2/posts",
        params={
            "per_page": LIST_PAGE_SIZE,
            "page": page,
            "status": "any",
            "context": "view",
            "_fields": "id,title,status",
        },
        auth=auth,
        timeout=60,
    )
    if resp.status_code == 400:
        return None
    resp.raise_for_status()
    posts = resp.json()
    return posts or None


def fetch_post_source(
    base: str, auth: tuple[str, str], post_id: int, *, retries: int = 2
) -> str | None:
    """Fetch rendered content for one post and extract source URL."""
    for attempt in range(retries):
        try:
            resp = SESSION.get(
                f"{base}/wp-json/wp/v2/posts/{post_id}",
                params={"context": "view", "_fields": "content"},
                auth=auth,
                timeout=CONTENT_TIMEOUT,
            )
        except requests.RequestException:
            if attempt + 1 >= retries:
                return None
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code != 200:
            return None
        content = resp.json().get("content", {}).get("rendered", "")
        return extract_source_url(content)
    return None


def sync_published_from_wp(*, dry_run: bool = False, max_posts: int = 80) -> dict:
    """Merge WP posts with «Источник» links into published.json.

    Scans the most recent *max_posts* posts (newest first). Lists posts in fast
    batches, then fetches content per post so slow entries do not block the rest.
    """
    wp = wp_config()
    auth = (wp["user"], wp["password"])
    base = wp["url"]

    by_url: dict[str, dict] = {
        e["source_url"]: dict(e) for e in load_published() if e.get("source_url")
    }
    added: list[dict] = []
    refreshed: list[dict] = []
    skipped: list[int] = []

    scanned = 0
    page = 1
    while scanned < max_posts:
        summaries = fetch_post_summaries(base, auth, page)
        if not summaries:
            break

        for post in summaries:
            if scanned >= max_posts:
                break
            scanned += 1
            source_url = fetch_post_source(base, auth, post["id"])
            if not source_url:
                if post.get("status") in ("draft", "publish"):
                    skipped.append(post["id"])
                continue
            entry = {
                "source_url": source_url,
                "wp_post_id": post["id"],
                "title": post.get("title", {}).get("rendered", ""),
                "status": post["status"],
            }
            prev = by_url.get(source_url)
            if not prev:
                by_url[source_url] = entry
                added.append(entry)
                continue
            if prev.get("wp_post_id") != post["id"] or prev.get("title") != entry["title"]:
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
        "scanned": scanned,
        "skipped_timeouts": len(skipped),
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
