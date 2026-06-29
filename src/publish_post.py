"""Publish a prepared article to WordPress via REST API."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from src.cta import build_cta_html
from src.content_filter import ensure_allowed
from src.lib import mark_published, wp_config, is_published

SESSION = requests.Session()
MORE_TAG = "<!--more-->"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(text, "html.parser").get_text()).strip()


def format_teaser(excerpt_ru: str) -> str:
    excerpt = excerpt_ru.strip()
    if not excerpt:
        return ""
    if excerpt.startswith("<"):
        return excerpt
    return f"<p>{html.escape(excerpt)}</p>"


def strip_leading_duplicate(body: str, excerpt_ru: str) -> str:
    excerpt_norm = normalize_text(excerpt_ru)
    if not excerpt_norm:
        return body

    match = re.match(r"^\s*<p[^>]*>(.*?)</p>", body, re.DOTALL | re.IGNORECASE)
    if match and normalize_text(match.group(1)) == excerpt_norm:
        return body[match.end() :].lstrip()

    soup = BeautifulSoup(body, "html.parser")
    first_p = soup.find("p")
    if first_p and normalize_text(first_p.get_text()) == excerpt_norm:
        first_p.decompose()
        return str(soup).strip()
    return body


def prepare_teaser_content(body_ru: str, excerpt_ru: str) -> str:
    """Split intro (blog listing) and full article like existing bl-school.com posts."""
    body = body_ru.strip()
    for marker in ("<!--MORE-->", MORE_TAG):
        if marker in body:
            before, after = body.split(marker, 1)
            teaser = before.strip() or format_teaser(excerpt_ru)
            return f"{teaser}\n{MORE_TAG}\n{after.lstrip()}"

    if excerpt_ru.strip():
        teaser = format_teaser(excerpt_ru)
        rest = strip_leading_duplicate(body, excerpt_ru)
        return f"{teaser}\n{MORE_TAG}\n{rest}"

    match = re.match(r"^(\s*<p[^>]*>.*?</p>)", body, re.DOTALL | re.IGNORECASE)
    if not match and body.lstrip().startswith("<!--HERO-->"):
        after_hero = body.lstrip()[len("<!--HERO-->") :].lstrip()
        p_match = re.match(r"^(\s*<p[^>]*>.*?</p>)", after_hero, re.DOTALL | re.IGNORECASE)
        if p_match:
            teaser = p_match.group(1).strip()
            rest = after_hero[p_match.end() :].lstrip()
            return f"<!--HERO-->\n{teaser}\n{MORE_TAG}\n{rest}"

    if match:
        teaser = match.group(1).strip()
        rest = body[match.end() :].lstrip()
        return f"{teaser}\n{MORE_TAG}\n{rest}"

    return body


def content_has_read_more(content: str) -> bool:
    return MORE_TAG in content


def strip_hero_marker(text: str) -> str:
    cleaned = text.replace("<!--HERO-->", "")
    return re.sub(r"^\s+", "", cleaned, flags=re.MULTILINE)


def place_hero_in_teaser(body: str, hero_fig: str) -> str:
    """Hero image before <!--more--> — visible in /blog/ catalog preview."""
    if MORE_TAG not in body:
        if hero_fig:
            return body.replace("<!--HERO-->", hero_fig)
        return strip_hero_marker(body)

    before, after = body.split(MORE_TAG, 1)
    after = strip_hero_marker(after)
    before = before.replace("<!--HERO-->", "").strip()

    if hero_fig:
        if "<img" not in before:
            before = f"{hero_fig}\n\n{before}".strip() if before else hero_fig
    return f"{before}\n{MORE_TAG}\n{after}"


def pick_hero(uploaded: list[dict], source_images: list[dict]) -> dict | None:
    if not uploaded:
        return None
    for u in uploaded:
        if u.get("role") == "hero":
            return u
    for i, img in enumerate(source_images):
        if img.get("role") == "hero" and i < len(uploaded):
            return uploaded[i]
    return uploaded[0]


def pick_inline_images(uploaded: list[dict], hero: dict | None) -> list[dict]:
    inline = [u for u in uploaded if u.get("role") == "inline"]
    if inline:
        return inline
    if not uploaded:
        return []
    if hero and hero in uploaded:
        return [u for u in uploaded if u is not hero]
    return uploaded[1:] if len(uploaded) > 1 else []


def upload_media(file_path: Path, wp: dict) -> tuple[int, str]:
    mime, _ = mimetypes.guess_type(file_path.name)
    mime = mime or "image/jpeg"
    with open(file_path, "rb") as f:
        resp = SESSION.post(
            f"{wp['url']}/wp-json/wp/v2/media",
            auth=(wp["user"], wp["password"]),
            headers={
                "Content-Disposition": f'attachment; filename="{file_path.name}"',
                "Content-Type": mime,
            },
            data=f.read(),
            timeout=60,
        )
    resp.raise_for_status()
    media = resp.json()
    return media["id"], media["source_url"]


def upload_images(images: list[dict], wp: dict) -> list[dict]:
    uploaded: list[dict] = []
    for img in images:
        path = Path(img["local_path"])
        if not path.exists():
            continue
        media_id, media_url = upload_media(path, wp)
        uploaded.append({**img, "media_id": media_id, "media_url": media_url})
    return uploaded


def pick_caption(img: dict) -> str:
    return (img.get("caption_ru") or img.get("caption") or "").strip()


def inline_figure(media_url: str, caption: str = "") -> str:
    cap = html.escape(caption.strip()) if caption else ""
    cap_html = (
        f'<figcaption class="wp-element-caption" style="text-align:center;color:#666;'
        f'font-size:14px;line-height:1.5;margin-top:10px;font-style:italic;">{cap}</figcaption>'
        if cap
        else ""
    )
    return (
        f'<figure class="wp-block-image size-large">'
        f'<img src="{media_url}" alt="" loading="lazy" '
        f'style="width:100%;height:auto;object-fit:contain;"/>'
        f"{cap_html}</figure>"
    )


def embed_inline_images(body: str, hero: dict | None, inline_images: list[dict]) -> str:
    html = body
    if hero:
        fig = inline_figure(hero["media_url"], pick_caption(hero))
        html = html.replace("<!--HERO-->", fig)
    for i, img in enumerate(inline_images):
        fig = inline_figure(img["media_url"], pick_caption(img))
        html = html.replace(f"<!--IMG:{i}-->", fig)
    return html


def build_content_html(
    body_ru: str,
    excerpt_ru: str,
    source_name: str,
    source_url: str,
    hero: dict | None,
    inline_images: list[dict],
) -> str:
    cta = build_cta_html()
    footer = (
        f'<hr style="border:none;border-top:1px solid #e8e8e8;margin:32px 0;">'
        f'<p style="color:#888;font-size:14px;"><em>Источник: '
        f'<a href="{source_url}" rel="nofollow noopener" target="_blank">{source_name}</a></em></p>'
    )

    body_with_teaser = prepare_teaser_content(body_ru, excerpt_ru)
    if not content_has_read_more(body_with_teaser) and excerpt_ru.strip():
        body_with_teaser = f"{format_teaser(excerpt_ru)}\n{MORE_TAG}\n{body_with_teaser}"

    body_with_teaser = embed_inline_images(body_with_teaser, None, inline_images)
    hero_fig = (
        inline_figure(hero["media_url"], pick_caption(hero)) if hero else ""
    )
    body_with_teaser = place_hero_in_teaser(body_with_teaser, hero_fig)

    if not content_has_read_more(body_with_teaser):
        raise ValueError(
            "Не удалось вставить <!--more-->: укажите --excerpt или начните body с абзаца <p>"
        )

    return "\n\n".join([body_with_teaser, cta, footer])


def prepare_post_payload(
    data: dict,
    title_ru: str,
    body_ru: str,
    excerpt_ru: str,
    wp: dict,
    uploaded: list[dict] | None = None,
) -> tuple[dict, list[dict]]:
    source = data["source"]
    if uploaded is None:
        uploaded = upload_images(data.get("images", []), wp)

    source_images = data.get("images", [])
    hero = pick_hero(uploaded, source_images)
    inline_images = pick_inline_images(uploaded, hero)

    # Hero во вступлении (до <!--more-->) — для превью в каталоге /blog/
    featured_media_id = None

    content = build_content_html(
        body_ru, excerpt_ru, source["name"], source["url"], hero, inline_images
    )

    payload: dict = {
        "title": title_ru,
        "content": content,
        "status": wp["status"],
        "categories": data.get("category_ids", [26]),
    }
    if excerpt_ru.strip():
        payload["excerpt"] = format_teaser(excerpt_ru)
    payload["featured_media"] = featured_media_id or 0
    slug = data.get("slug_ru") or data.get("suggested_slug")
    if slug:
        payload["slug"] = slug
    payload["_has_read_more"] = content_has_read_more(content)
    return payload, uploaded


def publish(
    article_path: Path,
    title_ru: str,
    body_ru: str,
    excerpt_ru: str = "",
    skip_filter: bool = False,
) -> dict:
    wp = wp_config()
    data = json.loads(article_path.read_text(encoding="utf-8"))
    if not skip_filter:
        ensure_allowed(
            title_ru,
            body_ru,
            excerpt_ru,
            data.get("title_en", ""),
            data.get("content_html_en", ""),
        )
    payload, uploaded = prepare_post_payload(data, title_ru, body_ru, excerpt_ru, wp)
    has_read_more = payload.pop("_has_read_more", False)

    source_url = data.get("source", {}).get("url", "")
    if source_url and is_published(source_url):
        raise RuntimeError(
            f"Статья уже опубликована (source_url в published.json): {source_url}. "
            "Используйте --update <post_id> или удалите дубликат."
        )

    resp = SESSION.post(
        f"{wp['url']}/wp-json/wp/v2/posts",
        auth=(wp["user"], wp["password"]),
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    post = resp.json()

    data["uploaded_media"] = uploaded
    article_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    mark_published(data["source"]["url"], post["id"], title_ru)
    return {
        "post_id": post["id"],
        "link": post["link"],
        "status": post["status"],
        "has_read_more": has_read_more,
    }


def update_post(
    post_id: int,
    article_path: Path,
    title_ru: str,
    body_ru: str,
    excerpt_ru: str = "",
    reuse_uploaded: bool = True,
    skip_filter: bool = False,
) -> dict:
    wp = wp_config()
    data = json.loads(article_path.read_text(encoding="utf-8"))
    if not skip_filter:
        ensure_allowed(
            title_ru,
            body_ru,
            excerpt_ru,
            data.get("title_en", ""),
            data.get("content_html_en", ""),
        )
    uploaded = data.get("uploaded_media") if reuse_uploaded else None
    if not uploaded:
        uploaded = None
    payload, uploaded = prepare_post_payload(
        data, title_ru, body_ru, excerpt_ru, wp, uploaded=uploaded
    )
    has_read_more = payload.pop("_has_read_more", False)

    resp = SESSION.post(
        f"{wp['url']}/wp-json/wp/v2/posts/{post_id}",
        auth=(wp["user"], wp["password"]),
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    post = resp.json()

    data["uploaded_media"] = uploaded
    article_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "post_id": post["id"],
        "link": post["link"],
        "status": post["status"],
        "has_read_more": has_read_more,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish article to WordPress")
    parser.add_argument("--article", required=True, type=Path, help="article.json path")
    parser.add_argument("--title", required=True, help="Russian title")
    parser.add_argument("--body-file", required=True, type=Path, help="Russian HTML body")
    parser.add_argument("--excerpt", default="", help="Russian excerpt")
    parser.add_argument("--update", type=int, help="Update existing post ID instead of creating")
    args = parser.parse_args()

    body = args.body_file.read_text(encoding="utf-8")
    if args.update:
        result = update_post(args.update, args.article, args.title, body, args.excerpt)
    else:
        result = publish(args.article, args.title, body, args.excerpt)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
