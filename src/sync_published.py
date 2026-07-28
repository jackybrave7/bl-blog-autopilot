"""Sync data/published.json from existing WordPress posts (source links)."""

from __future__ import annotations

import argparse
import json
import re
import time

import requests

from src.lib import PUBLISHED_FILE, load_published, save_published, wp_config

SESSION = requests.Session()
# WP on bl-school.com times out on large batches with context=edit (heavy raw HTML).
WP_SYNC_PER_PAGE = 1
WP_SYNC_TIMEOUT = 120
SOURCE_LINK_RE = re.compile(
    r'Источник:\s*<a\s+href="([^"]+)"',
    re.IGNORECASE,
)


def extract_source_url(content: str) -> str | None:
    match = SOURCE_LINK_RE.search(content)
    return match.group(1).strip() if match else None


def _fetch_posts_page(
    base: str,
    auth: tuple[str, str],
    page: int,
    *,
    max_attempts: int = 4,
) -> requests.Response:
    """Fetch one WP posts page; retry on read timeouts."""
    params = {
        "per_page": WP_SYNC_PER_PAGE,
        "page": page,
        "status": "any",
        "context": "edit",
    }
    for attempt in range(1, max_attempts + 1):
        try:
            resp = SESSION.get(
                f"{base}/wp-json/wp/v2/posts",
                params=params,
                auth=auth,
                timeout=WP_SYNC_TIMEOUT,
            )
            if resp.status_code == 400:
                return resp
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == max_attempts:
                raise
            time.sleep(4 * attempt)
    raise RuntimeError("unreachable")


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

    page = 1
    while True:
        resp = _fetch_posts_page(base, auth, page)
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        posts = resp.json()
        if not posts:
            break

        for post in posts:
            source_url = extract_source_url(post["content"]["raw"])
            if not source_url:
                continue
            entry = {
                "source_url": source_url,
                "wp_post_id": post["id"],
                "title": post["title"]["raw"],
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
