"""Shared helpers for bl-blog-autopilot."""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
PENDING_DIR = DATA_DIR / "pending"
PUBLISHED_FILE = DATA_DIR / "published.json"
SKIPPED_FILE = DATA_DIR / "skipped.json"


def load_env() -> None:
    load_dotenv(ROOT / ".env")


def wp_config() -> dict:
    load_env()
    return {
        "url": os.environ["WP_URL"].rstrip("/"),
        "user": os.environ["WP_USER"],
        "password": os.environ["WP_APP_PASSWORD"].replace(" ", ""),
        "status": os.environ.get("WP_POST_STATUS", "draft"),
        "cta_html": os.environ.get("CTA_HTML", ""),
    }


def load_sources() -> list[dict]:
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["sources"]


def load_published() -> list[dict]:
    if not PUBLISHED_FILE.exists():
        return []
    with open(PUBLISHED_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_published(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PUBLISHED_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def is_published(url: str) -> bool:
    return any(e.get("source_url") == url for e in load_published())


def load_skipped() -> list[dict]:
    if not SKIPPED_FILE.exists():
        return []
    with open(SKIPPED_FILE, encoding="utf-8") as f:
        return json.load(f)


def is_skipped(url: str) -> bool:
    return any(e.get("source_url") == url for e in load_skipped())


def mark_skipped(source_url: str, reason: str, category: str, title: str = "") -> None:
    entries = load_skipped()
    if any(e.get("source_url") == source_url for e in entries):
        return
    entries.append(
        {
            "source_url": source_url,
            "category": category,
            "reason": reason,
            "title": title,
        }
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SKIPPED_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def load_pending_meta(article_path: Path) -> dict:
    """Read meta.json next to article.json (title_ru, excerpt_ru, slug_ru)."""
    meta_path = article_path.parent / "meta.json"
    if not meta_path.exists():
        return {}
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def resolve_publish_fields(article_path: Path, title: str = "", excerpt: str = "") -> tuple[str, str]:
    """Merge CLI args with meta.json and article.json for title and excerpt."""
    meta = load_pending_meta(article_path)
    article: dict = {}
    if article_path.exists():
        with open(article_path, encoding="utf-8") as f:
            article = json.load(f)

    resolved_title = title or meta.get("title_ru") or article.get("title_ru") or ""
    resolved_excerpt = (
        excerpt or meta.get("excerpt_ru") or article.get("excerpt_ru") or ""
    )
    return resolved_title.strip(), resolved_excerpt.strip()


def mark_published(source_url: str, wp_post_id: int, title: str) -> None:
    entries = load_published()
    entries.append(
        {
            "source_url": source_url,
            "wp_post_id": wp_post_id,
            "title": title,
        }
    )
    save_published(entries)
