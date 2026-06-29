"""Fetch the next unpublished article from configured RSS sources."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from readability import Document

from src.lib import (
    PENDING_DIR,
    is_published,
    is_skipped,
    load_sources,
    mark_skipped,
)
from src.content_filter import find_blocked_topic

USER_AGENT = (
    "Mozilla/5.0 (compatible; BLBlogAutopilot/1.0; +https://www.bl-school.com/blog)"
)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

RSS_TIMEOUT = (5, 10)
ARTICLE_TIMEOUT = (5, 20)


def log(msg: str) -> None:
    print(msg, flush=True)


def sources_for_today(weekday: int | None = None) -> list[dict]:
    wd = weekday if weekday is not None else datetime.now().weekday()
    all_sources = load_sources()
    today = [s for s in all_sources if wd in s.get("weekdays", list(range(7)))]
    return today or all_sources


def parse_feed(url: str) -> feedparser.FeedParserDict:
    resp = SESSION.get(url, timeout=RSS_TIMEOUT)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def pick_entry(source: dict) -> feedparser.FeedParserDict | None:
    feed = parse_feed(source["url"])
    for entry in feed.entries:
        link = entry.get("link")
        if link and not is_published(link) and not is_skipped(link):
            return entry
    return None


def fullsize_image_url(url: str) -> str:
    return re.sub(r"/size/w\d+/", "/", url)


def extract_images_structured(page_url: str) -> list[dict]:
    """Hero (og:image) + inline figures with captions, in article order."""
    resp = SESSION.get(page_url, timeout=ARTICLE_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    images: list[dict] = []

    og = soup.find("meta", property="og:image")
    header_cap = soup.select_one(
        ".gh-article-header figure figcaption, .gh-article-image figcaption"
    )
    hero_caption = header_cap.get_text(" ", strip=True) if header_cap else ""
    if og and og.get("content"):
        images.append(
            {
                "role": "hero",
                "source_url": fullsize_image_url(og["content"]),
                "caption": hero_caption,
            }
        )

    for fig in soup.select(".gh-content figure.kg-image-card"):
        img = fig.find("img")
        if not img or not img.get("src"):
            continue
        cap_el = fig.find("figcaption")
        images.append(
            {
                "role": "inline",
                "source_url": img["src"],
                "caption": cap_el.get_text(" ", strip=True) if cap_el else "",
            }
        )
    return images


def download_images_structured(image_meta: list[dict], dest: Path) -> list[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for i, meta in enumerate(image_meta):
        url = meta["source_url"]
        try:
            resp = SESSION.get(url, timeout=ARTICLE_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestError:
            continue
        ext = Path(urlparse(url).path).suffix or ".jpg"
        if len(ext) > 5:
            ext = ".jpg"
        filename = f"img_{i:02d}{ext}"
        path = dest / filename
        path.write_bytes(resp.content)
        saved.append({**meta, "local_path": str(path), "filename": filename})
    return saved


def extract_images(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        full = urljoin(base_url, src)
        if full in seen:
            continue
        if any(x in full.lower() for x in ("pixel", "tracking", "avatar", "logo-icon")):
            continue
        seen.add(full)
        urls.append(full)
    return urls[:8]


def resolve_digest_url(url: str) -> str:
    """If RSS points to a newsletter digest, follow the first linked article."""
    try:
        resp = SESSION.get(url, timeout=ARTICLE_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return url
    if "daily-newsletter" not in resp.text.lower():
        return url
    soup = BeautifulSoup(resp.text, "lxml")
    base_path = urlparse(url).path.strip("/")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "hyperallergic.com/" not in href:
            continue
        if any(x in href for x in ("/tag/", "/author/", "/feed", "newsletter")):
            continue
        path = urlparse(href).path.strip("/")
        if path and path != base_path:
            log(f"  ↳ дайджест → {href}")
            return href
    return url


def fetch_article_html(url: str) -> tuple[str, str]:
    url = resolve_digest_url(url)
    resp = SESSION.get(url, timeout=ARTICLE_TIMEOUT)
    resp.raise_for_status()
    doc = Document(resp.text)
    title = doc.title().strip()
    content_html = doc.summary(html_partial=True)
    return title, content_html


def download_images(image_urls: list[str], dest: Path) -> list[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for i, url in enumerate(image_urls):
        try:
            resp = SESSION.get(url, timeout=ARTICLE_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestError:
            continue
        ext = Path(urlparse(url).path).suffix or ".jpg"
        if len(ext) > 5:
            ext = ".jpg"
        filename = f"img_{i:02d}{ext}"
        path = dest / filename
        path.write_bytes(resp.content)
        saved.append({
            "local_path": str(path),
            "source_url": url,
            "filename": filename,
            "role": "hero" if i == 0 else "inline",
        })
    return saved


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:80].strip("-")


def fetch_next(weekday: int | None = None) -> dict:
    from src.sync_published import sync_published_from_wp

    sync = sync_published_from_wp()
    if sync["added"]:
        log(f"Синхронизация WP: +{sync['added']} URL в published.json")

    errors: list[str] = []
    today_sources = sources_for_today(weekday)
    all_sources = load_sources()
    passes = [today_sources]
    if today_sources != all_sources:
        passes.append(all_sources)

    for pass_idx, source_list in enumerate(passes):
        if pass_idx == 1:
            log("Источники дня недоступны, пробую остальные…")
        for source in source_list:
            log(f"→ {source['name']}…")
            try:
                entry = pick_entry(source)
            except requests.RequestException as exc:
                log(f"  ✗ RSS: {exc.__class__.__name__}")
                errors.append(f"{source['id']}: RSS {exc}")
                continue
            if not entry:
                log("  — нет новых статей")
                continue
            url = entry["link"]
            title_from_feed = entry.get("title", "")
            log(f"  ✓ статья: {title_from_feed[:60]}…")
            try:
                title, content_html = fetch_article_html(url)
            except requests.RequestException as exc:
                log(f"  ✗ страница: {exc.__class__.__name__}")
                errors.append(f"{source['id']}: article {exc}")
                continue
            if not title:
                title = title_from_feed
            blocked = find_blocked_topic(title_from_feed, title, content_html)
            if blocked:
                category, label, keyword = blocked
                log(f"  ⊘ стоп-тема «{label}»: {keyword}")
                mark_skipped(url, f"{label}: {keyword}", category, title or title_from_feed)
                continue
            image_meta = extract_images_structured(url)
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            pending_dir = PENDING_DIR / run_id
            image_files = download_images_structured(image_meta, pending_dir)
            log(f"  ✓ скачано картинок: {len(image_files)}")
            return {
                "run_id": run_id,
                "source": {
                    "id": source["id"],
                    "name": source["name"],
                    "url": url,
                },
                "category_ids": source.get("category_ids", [26]),
                "title_en": title,
                "content_html_en": content_html,
                "images": image_files,
                "suggested_slug": slugify(title),
            }
    detail = "; ".join(errors) if errors else "all feeds empty or already published"
    raise RuntimeError(f"No unpublished articles found in today's sources. ({detail})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch next article for translation")
    parser.add_argument("--weekday", type=int, help="0=Mon … 6=Sun (default: today)")
    parser.add_argument("--out", type=Path, help="Output JSON path")
    args = parser.parse_args()

    article = fetch_next(args.weekday)
    out = args.out or PENDING_DIR / article["run_id"] / "article.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out), "title": article["title_en"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
