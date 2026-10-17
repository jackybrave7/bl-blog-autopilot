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
from src.content_focus import (
    check_url_allowed,
    entry_preview_text,
    is_source_blocked,
    score_text,
)

USER_AGENT = (
    "Mozilla/5.0 (compatible; BLBlogAutopilot/1.0; +https://www.bl-school.com/blog)"
)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

RSS_TIMEOUT = (5, 10)
ARTICLE_TIMEOUT = (5, 20)


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)


def sort_sources(sources: list[dict]) -> list[dict]:
    """Lower priority number = try earlier (1 = illustration/craft feeds)."""
    return sorted(sources, key=lambda s: (s.get("priority", 2), s.get("id", "")))


def sources_for_today(weekday: int | None = None) -> list[dict]:
    wd = weekday if weekday is not None else datetime.now().weekday()
    all_sources = sort_sources(load_sources())
    today = [s for s in all_sources if wd in s.get("weekdays", list(range(7)))]
    return sort_sources(today) if today else all_sources


def parse_feed(url: str) -> feedparser.FeedParserDict:
    resp = SESSION.get(url, timeout=RSS_TIMEOUT)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def load_active_sources(weekday: int | None = None) -> list[dict]:
    return [s for s in sources_for_today(weekday) if not is_source_blocked(s.get("id", ""))]


def pick_entry(source: dict) -> feedparser.FeedParserDict | None:
    if is_source_blocked(source.get("id", "")):
        return None
    feed = parse_feed(source["url"])
    candidates: list[tuple[int, feedparser.FeedParserDict]] = []
    priority_bonus = max(0, 4 - int(source.get("priority", 2))) * 5

    for entry in feed.entries:
        link = entry.get("link")
        if not link or is_published(link) or is_skipped(link):
            continue
        url_block = check_url_allowed(link)
        if url_block:
            title = (entry.get("title") or "")[:60]
            log(f"  ⊘ {url_block}: {title}…")
            mark_skipped(link, url_block, "off-topic", entry.get("title", ""))
            continue
        preview = entry_preview_text(entry)
        article_score, skip_reason = score_text(preview)
        if skip_reason:
            title = (entry.get("title") or "")[:60]
            log(f"  ⊘ {skip_reason}: {title}…")
            mark_skipped(link, skip_reason, "off-topic", entry.get("title", ""))
            continue
        candidates.append((article_score + priority_bonus, entry))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def html_to_plain(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(" ", strip=True)


def fullsize_image_url(url: str) -> str:
    url = re.sub(r"/size/w\d+/", "/", url)
    # WordPress.com / Illustration Age: ?w=700 → full path
    if "?w=" in url or "&w=" in url:
        url = url.split("?")[0].split("&")[0]
    # WordPress thumbnails: image-300x200.jpg → image.jpg
    url = re.sub(r"-\d+x\d+(\.(?:jpe?g|png|gif|webp))", r"\1", url, flags=re.IGNORECASE)
    return url


def _is_junk_image(url: str, img_tag) -> bool:
    lower = url.lower()
    if any(x in lower for x in (
        "gravatar", "pixel", "tracking", "avatar", "logo", "emoji",
        "spinner", "badge", "wp-smiley", "icon.svg", "doubleclick",
    )):
        return True
    try:
        w = int(img_tag.get("width") or 0)
        h = int(img_tag.get("height") or 0)
        if w and h and w < 64 and h < 64:
            return True
    except (TypeError, ValueError):
        pass
    return False


def _img_src(img) -> str | None:
    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
        val = img.get(attr)
        if val and not val.startswith("data:"):
            return val
    return None


def _dedupe_image_meta(images: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for meta in images:
        key = fullsize_image_url(meta["source_url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append({**meta, "source_url": key})
    return unique


def _extract_ghost_figures(soup: BeautifulSoup) -> list[dict]:
    images: list[dict] = []
    for fig in soup.select(".gh-content figure.kg-image-card"):
        img = fig.find("img")
        if not img:
            continue
        src = _img_src(img)
        if not src or _is_junk_image(src, img):
            continue
        cap_el = fig.find("figcaption")
        images.append({
            "role": "inline",
            "source_url": fullsize_image_url(urljoin("", src)),
            "caption": cap_el.get_text(" ", strip=True) if cap_el else "",
        })
    return images


def _extract_wordpress_figures(soup: BeautifulSoup, base_url: str) -> list[dict]:
    root = (
        soup.select_one(".entry")
        or soup.select_one(".hentry")
        or soup.select_one("article .post-content")
        or soup.select_one("article")
        or soup.select_one("main")
    )
    if not root:
        return []

    images: list[dict] = []
    seen_in_figure: set[str] = set()

    for fig in root.find_all("figure"):
        img = fig.find("img")
        if not img:
            continue
        src = _img_src(img)
        if not src or _is_junk_image(src, img):
            continue
        full = fullsize_image_url(urljoin(base_url, src))
        seen_in_figure.add(full)
        cap_el = fig.find("figcaption")
        images.append({
            "role": "inline",
            "source_url": full,
            "caption": cap_el.get_text(" ", strip=True) if cap_el else "",
        })

    for img in root.find_all("img"):
        src = _img_src(img)
        if not src or _is_junk_image(src, img):
            continue
        full = fullsize_image_url(urljoin(base_url, src))
        if full in seen_in_figure:
            continue
        images.append({
            "role": "inline",
            "source_url": full,
            "caption": img.get("alt", "").strip(),
        })

    return images


def extract_images_structured(page_url: str) -> list[dict]:
    """Hero (og:image) + inline figures from Ghost, WordPress, or generic article."""
    resp = SESSION.get(page_url, timeout=ARTICLE_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    base_url = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"

    header_cap = ""
    header_cap_el = soup.select_one(
        ".gh-article-header figure figcaption, .gh-article-image figcaption"
    )
    if header_cap_el:
        header_cap = header_cap_el.get_text(" ", strip=True)

    content_images = _extract_ghost_figures(soup)
    if len(content_images) < 2:
        content_images = _dedupe_image_meta(
            content_images + _extract_wordpress_figures(soup, base_url)
        )

    if len(content_images) < 2:
        doc = Document(resp.text)
        content_images = _dedupe_image_meta(
            content_images
            + [
                {
                    "role": "inline",
                    "source_url": fullsize_image_url(urljoin(base_url, u)),
                    "caption": "",
                }
                for u in extract_images(doc.summary(html_partial=True), base_url)
            ]
        )

    content_images = _dedupe_image_meta(content_images)[:23]

    og = soup.find("meta", property="og:image")
    og_url = fullsize_image_url(og["content"]) if og and og.get("content") else None

    images: list[dict] = []
    if og_url:
        images.append({
            "role": "hero",
            "source_url": og_url,
            "caption": header_cap,
        })
        content_images = [
            c for c in content_images
            if fullsize_image_url(c["source_url"]) != og_url
        ]
    elif content_images:
        first = content_images.pop(0)
        images.append({**first, "role": "hero", "caption": first.get("caption", "")})

    for item in content_images:
        images.append({**item, "role": "inline"})

    return images[:24]


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
    return urls[:24]


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

    try:
        sync = sync_published_from_wp()
        if sync["added"]:
            log(f"Синхронизация WP: +{sync['added']} URL в published.json")
    except requests.RequestException as exc:
        log(f"⚠ Синхронизация WP не удалась ({exc.__class__.__name__}), использую published.json")

    errors: list[str] = []
    today_sources = load_active_sources(weekday)
    all_sources = [s for s in sort_sources(load_sources()) if not is_source_blocked(s.get("id", ""))]
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
            url_block = check_url_allowed(url)
            if url_block:
                log(f"  ⊘ {url_block}")
                mark_skipped(url, url_block, "off-topic", title_from_feed)
                continue
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
            focus_score, focus_skip = score_text(title_from_feed, title, html_to_plain(content_html))
            if focus_skip:
                log(f"  ⊘ {focus_skip}")
                mark_skipped(url, focus_skip, "off-topic", title or title_from_feed)
                continue
            log(f"  ✓ фокус score={focus_score}")
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
