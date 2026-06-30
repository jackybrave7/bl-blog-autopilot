"""Re-download images from source and rebuild a published WP post."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from src.fetch_article import download_images_structured, extract_images_structured
from src.lib import load_env, wp_config
from src.publish_post import prepare_post_payload, update_post

load_env()


def source_url_from_content(content: str) -> str | None:
    m = re.search(r'href="([^"]+)"[^>]*rel="nofollow', content)
    return m.group(1) if m else None


def body_without_media_and_footer(content: str) -> str:
    if "<!--more-->" in content:
        body = content.split("<!--more-->", 1)[1]
    else:
        body = content

    for marker in ("bl-cta-banner", "<hr", "Источник:"):
        idx = body.find(marker)
        if idx > 0:
            body = body[:idx]

    soup = BeautifulSoup(body, "html.parser")
    for tag in soup.find_all(["figure", "img"]):
        tag.decompose()
    return str(soup).strip()


def teaser_from_content(content: str) -> str:
    if "<!--more-->" not in content:
        return ""
    return content.split("<!--more-->", 1)[0].strip()


def repair_post(post_id: int, *, dry_run: bool = False) -> dict:
    wp = wp_config()
    auth = (wp["user"], wp["password"])
    base = wp["url"]

    resp = requests.get(
        f"{base}/wp-json/wp/v2/posts/{post_id}",
        params={"context": "edit"},
        auth=auth,
        timeout=60,
    )
    resp.raise_for_status()
    post = resp.json()
    raw = post["content"]["raw"]
    src = source_url_from_content(raw)
    if not src:
        raise RuntimeError(f"Post {post_id}: no source URL in content")

    image_meta = extract_images_structured(src)
    pending_dir = Path("data/pending") / f"repair_{post_id}"
    images = download_images_structured(image_meta, pending_dir)

    article = {
        "source": {
            "id": "repair",
            "name": "Illustration Age",
            "url": src,
        },
        "category_ids": post.get("categories", [26]),
        "title_en": post["title"]["raw"],
        "images": images,
        "slug_ru": post["slug"],
    }
    article_path = pending_dir / "article.json"
    article_path.parent.mkdir(parents=True, exist_ok=True)
    article_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")

    title_ru = post["title"]["raw"]
    excerpt_ru = BeautifulSoup(
        post.get("excerpt", {}).get("raw", "") or teaser_from_content(raw),
        "html.parser",
    ).get_text(" ", strip=True)
    body_ru = body_without_media_and_footer(raw)

    result = {
        "post_id": post_id,
        "source": src,
        "images_found": len(image_meta),
        "images_downloaded": len(images),
        "dry_run": dry_run,
    }

    if dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    payload, uploaded = prepare_post_payload(
        article, title_ru, body_ru, excerpt_ru, wp, uploaded=None
    )
    payload.pop("_has_read_more", None)

    upd = requests.post(
        f"{base}/wp-json/wp/v2/posts/{post_id}",
        auth=auth,
        json=payload,
        timeout=120,
    )
    upd.raise_for_status()

    article["uploaded_media"] = uploaded
    article_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")

    result["link"] = upd.json()["link"]
    result["img_tags_in_content"] = upd.json()["content"]["raw"].count("<img")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair images on published WP post")
    parser.add_argument("post_id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repair_post(args.post_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
