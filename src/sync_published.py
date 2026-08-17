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
WP_SYNC_PER_PAGE = 5
WP_SYNC_TIMEOUT = 30
WP_SYNC_RETRIES = 3
WP_SYNC_MAX_PUBLISH_PAGES = 30
WP_SYNC_MAX_DRAFT_PAGES = 15


def extract_source_url(content: str) -> str | None:
    match = SOURCE_LINK_RE.search(content)
    return match.group(1).strip() if match else None


def _fetch_posts_page(
    base: str,
    auth: tuple[str, str],
    *,
    page: int,
    status: str,
    orderby: str | None = None,
    order: str | None = None,
) -> list[dict] | None:
    last_error: Exception | None = None
    params: dict[str, str | int] = {
        "per_page": WP_SYNC_PER_PAGE,
        "page": page,
        "status": status,
        "_fields": "id,title,status,content",
    }
    if orderby:
        params["orderby"] = orderby
    if order:
        params["order"] = order
    for attempt in range(1, WP_SYNC_RETRIES + 1):
        try:
            resp = requests.get(
                f"{base}/wp-json/wp/v2/posts",
                params=params,
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
    if last_error:
        print(
            json.dumps(
                {
                    "warning": "wp_sync_page_failed",
                    "status": status,
                    "page": page,
                    "error": last_error.__class__.__name__,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return None


def sync_published_from_wp(*, dry_run: bool = False) -> dict:
    """Merge WP posts with «Источник» links into published.json."""
    wp = wp_config()
    auth = (wp["user"], wp["password"])
    base = wp["url"]

    existing = load_published()
    by_url: dict[str, dict] = {
        e["source_url"]: dict(e) for e in existing if e.get("source_url")
    }
    added: list[dict] = []
    refreshed: list[dict] = []
    warnings: list[dict] = []

    status_filters: list[dict[str, str | int]] = [
        {"status": "draft"},
        {"status": "publish", "orderby": "date", "order": "desc"},
    ]
    publish_page_limit = WP_SYNC_MAX_PUBLISH_PAGES
    draft_page_limit = WP_SYNC_MAX_DRAFT_PAGES

    for filters in status_filters:
        page = 1
        while True:
            if filters["status"] == "publish" and page > publish_page_limit:
                break
            if filters["status"] == "draft" and page > draft_page_limit:
                break
            posts = _fetch_posts_page(base, auth, page=page, **filters)
            if posts is None:
                warnings.append({"status": filters["status"], "page": page, "error": "timeout"})
                break
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
    if not dry_run and len(entries) >= len(existing):
        save_published(entries)
    elif not dry_run and len(entries) < len(existing):
        warnings.append(
            {
                "error": "sync_would_shrink_published_json",
                "existing": len(existing),
                "merged": len(entries),
            }
        )

    return {
        "total": len(entries),
        "added": len(added),
        "refreshed": len(refreshed),
        "added_posts": added,
        "refreshed_posts": refreshed,
        "warnings": warnings,
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
