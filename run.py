#!/usr/bin/env python3
"""CLI entry point for bl-blog-autopilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_fetch(weekday: int | None, out: Path | None, skip_sync: bool = False) -> None:
    from src.fetch_article import fetch_next

    article = fetch_next(weekday, skip_sync=skip_sync)
    path = out or Path("data/pending") / article["run_id"] / "article.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(path), "title": article["title_en"]}, ensure_ascii=False))


def cmd_publish(
    article: Path,
    title: str,
    body_file: Path,
    excerpt: str,
    update: int | None,
    force: bool,
) -> None:
    from src.lib import resolve_publish_fields
    from src.publish_post import publish, update_post

    title, excerpt = resolve_publish_fields(article, title, excerpt)
    if not title:
        raise SystemExit("Укажите --title или сохраните title_ru в meta.json рядом с article.json")
    if not excerpt:
        raise SystemExit(
            "Укажите --excerpt (вступительная часть для каталога /blog/) "
            "или сохраните excerpt_ru в meta.json"
        )

    body = body_file.read_text(encoding="utf-8")
    if update:
        result = update_post(update, article, title, body, excerpt, skip_filter=force)
    else:
        result = publish(article, title, body, excerpt, skip_filter=force)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


def cmd_check(title: str, body_file: Path | None, text: str | None) -> None:
    from src.content_filter import find_blocked_topic

    body = body_file.read_text(encoding="utf-8") if body_file else (text or "")
    hit = find_blocked_topic(title, body)
    if hit:
        category, label, keyword = hit
        print(json.dumps({"ok": False, "category": category, "label": label, "keyword": keyword}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps({"ok": True, "allowed": True}, ensure_ascii=False))


def cmd_translate(article: Path, force: bool) -> None:
    from src.translate import translate_article

    result = translate_article(article, skip_filter=force)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


def cmd_categorize(article: Path) -> None:
    from src.translate import categorize_article

    result = categorize_article(article)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


def cmd_backfill_cta(status: str, dry_run: bool, limit: int | None) -> None:
    from src.backfill_cta import backfill_cta

    if status == "any":
        r1 = backfill_cta(status="publish", dry_run=dry_run, limit=limit)
        r2 = backfill_cta(status="draft", dry_run=dry_run, limit=limit)
        result = {
            "ok": True,
            "dry_run": dry_run,
            "updated": r1["updated"] + r2["updated"],
            "skipped": r1["skipped"] + r2["skipped"],
            "posts_updated": r1["posts_updated"] + r2["posts_updated"],
        }
    else:
        result = {"ok": True, **backfill_cta(status=status, dry_run=dry_run, limit=limit)}
    print(json.dumps(result, ensure_ascii=False))


def cmd_sync_published(dry_run: bool) -> None:
    from src.sync_published import sync_published_from_wp

    result = sync_published_from_wp(dry_run=dry_run)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bratec Lis School blog autopilot")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch next article from RSS")
    fetch_p.add_argument("--weekday", type=int, help="0=Mon … 6=Sun")
    fetch_p.add_argument("--out", type=Path)
    fetch_p.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip WordPress sync (use when published.json is already up to date)",
    )

    pub_p = sub.add_parser("publish", help="Publish translated article to WordPress")
    pub_p.add_argument("--article", required=True, type=Path)
    pub_p.add_argument("--title", default="", help="Заголовок (или title_ru в meta.json)")
    pub_p.add_argument("--body-file", required=True, type=Path)
    pub_p.add_argument(
        "--excerpt",
        default="",
        help="Вступление для каталога /blog/ (или excerpt_ru в meta.json)",
    )
    pub_p.add_argument("--update", type=int, help="Update existing WP post ID")
    pub_p.add_argument("--force", action="store_true", help="Skip stop-topics filter")

    check_p = sub.add_parser("check", help="Check text against stop-topics filter")
    check_p.add_argument("--title", default="")
    check_p.add_argument("--body-file", type=Path)
    check_p.add_argument("--text", default="")

    tr_p = sub.add_parser("translate", help="Translate article via DeepSeek API")
    tr_p.add_argument("--article", required=True, type=Path)
    tr_p.add_argument("--force", action="store_true", help="Skip stop-topics filter")

    cat_p = sub.add_parser("categorize", help="Assign WP categories via DeepSeek")
    cat_p.add_argument("--article", required=True, type=Path)

    cta_p = sub.add_parser("backfill-cta", help="Add CTA banner to existing WP posts")
    cta_p.add_argument("--status", default="publish", help="publish | draft | any")
    cta_p.add_argument("--dry-run", action="store_true")
    cta_p.add_argument("--limit", type=int)

    sync_p = sub.add_parser("sync-published", help="Sync published.json from WordPress source links")
    sync_p.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "fetch":
        cmd_fetch(args.weekday, args.out, args.skip_sync)
    elif args.command == "publish":
        cmd_publish(args.article, args.title, args.body_file, args.excerpt, args.update, args.force)
    elif args.command == "check":
        cmd_check(args.title, args.body_file, args.text or None)
    elif args.command == "translate":
        cmd_translate(args.article, args.force)
    elif args.command == "categorize":
        cmd_categorize(args.article)
    elif args.command == "backfill-cta":
        cmd_backfill_cta(args.status, args.dry_run, args.limit)
    elif args.command == "sync-published":
        cmd_sync_published(args.dry_run)


if __name__ == "__main__":
    main()
