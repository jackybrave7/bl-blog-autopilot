"""Backfill CTA banner into existing WordPress posts."""

from __future__ import annotations

import argparse
import json
import time

import requests

from src.cta import inject_cta_html
from src.lib import load_env, wp_config

SESSION = requests.Session()


def iter_posts(wp: dict, status: str = "publish") -> list[dict]:
    posts: list[dict] = []
    page = 1
    while True:
        resp = SESSION.get(
            f"{wp['url']}/wp-json/wp/v2/posts",
            params={
                "per_page": 100,
                "page": page,
                "status": status,
                "context": "edit",
                "_fields": "id,title,content,status,link",
            },
            auth=(wp["user"], wp["password"]),
            timeout=60,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        posts.extend(batch)
        total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1
    return posts


def backfill_cta(
    status: str = "publish",
    dry_run: bool = False,
    limit: int | None = None,
    delay: float = 0.3,
) -> dict:
    load_env()
    wp = wp_config()
    posts = iter_posts(wp, status=status)
    updated: list[dict] = []
    skipped: list[dict] = []

    for post in posts:
        if limit is not None and len(updated) >= limit:
            break
        post_id = post["id"]
        raw = post["content"]["raw"]
        new_content = inject_cta_html(raw)
        if new_content == raw:
            skipped.append({"id": post_id, "title": post["title"]["raw"]})
            continue
        if dry_run:
            updated.append({"id": post_id, "title": post["title"]["raw"], "link": post["link"]})
            continue
        resp = SESSION.post(
            f"{wp['url']}/wp-json/wp/v2/posts/{post_id}",
            auth=(wp["user"], wp["password"]),
            json={"content": new_content},
            timeout=60,
        )
        resp.raise_for_status()
        updated.append({"id": post_id, "title": post["title"]["raw"], "link": post["link"]})
        time.sleep(delay)

    return {
        "status": status,
        "dry_run": dry_run,
        "updated": len(updated),
        "skipped": len(skipped),
        "posts_updated": updated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert CTA banner into WP posts")
    parser.add_argument("--status", default="publish", help="publish | draft | any")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Max posts to update")
    args = parser.parse_args()

    if args.status == "any":
        result = backfill_cta(status="publish", dry_run=args.dry_run, limit=args.limit)
        draft = backfill_cta(status="draft", dry_run=args.dry_run, limit=args.limit)
        result["updated"] += draft["updated"]
        result["skipped"] += draft["skipped"]
        result["posts_updated"].extend(draft["posts_updated"])
    else:
        result = backfill_cta(
            status=args.status,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
