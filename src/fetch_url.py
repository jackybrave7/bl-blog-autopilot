"""Fetch a specific article URL (bypass RSS)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.fetch_article import (
    download_images_structured,
    extract_images_structured,
    fetch_article_html,
    slugify,
)
from src.content_filter import ensure_allowed
from src.lib import PENDING_DIR


def fetch_url(url: str, source_name: str = "Hyperallergic", category_ids: list[int] | None = None) -> dict:
    title, content_html = fetch_article_html(url)
    ensure_allowed(title, content_html)
    image_meta = extract_images_structured(url)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    pending_dir = PENDING_DIR / run_id
    image_files = download_images_structured(image_meta, pending_dir)
    return {
        "run_id": run_id,
        "source": {"id": "manual", "name": source_name, "url": url},
        "category_ids": category_ids or [119, 9],
        "title_en": title,
        "content_html_en": content_html,
        "images": image_files,
        "suggested_slug": slugify(title),
        "uploaded_media": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    article = fetch_url(args.url)
    out = args.out or PENDING_DIR / article["run_id"] / "article.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(out),
                "title": article["title_en"],
                "images": len(article["images"]),
                "hero": sum(1 for i in article["images"] if i.get("role") == "hero"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
