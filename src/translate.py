"""Translate and adapt articles via DeepSeek API."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

from src.categories import (
    categorize_with_deepseek,
    category_names_for_ids,
    format_categories_for_prompt,
    resolve_category_ids,
)
from src.content_filter import ensure_allowed, find_blocked_topic
from src.lib import ROOT, load_env

SESSION = requests.Session()
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TRANSLATE_MODEL = "deepseek-v4-pro"
DEFAULT_CATEGORIZE_MODEL = "deepseek-v4-flash"


def deepseek_config() -> dict:
    load_env()
    import os

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY не задан в .env")
    translate_model = (
        os.environ.get("DEEPSEEK_TRANSLATE_MODEL", "").strip()
        or DEFAULT_TRANSLATE_MODEL
    )
    categorize_model = (
        os.environ.get("DEEPSEEK_CATEGORIZE_MODEL", "").strip()
        or os.environ.get("DEEPSEEK_MODEL", "").strip()
        or DEFAULT_CATEGORIZE_MODEL
    )
    return {
        "api_key": key,
        "translate_model": translate_model,
        "categorize_model": categorize_model,
        "timeout": int(os.environ.get("DEEPSEEK_TIMEOUT", "180")),
    }


def load_prompt_config() -> dict:
    path = ROOT / "config" / "translate_prompt.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def html_to_source_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()

    blocks: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "li"]):
        text = el.get_text(" ", strip=True)
        if text:
            blocks.append(text)
    if blocks:
        return "\n\n".join(blocks)

    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def format_images_list(images: list[dict]) -> str:
    lines: list[str] = []
    for i, img in enumerate(images):
        role = img.get("role", "inline")
        caption = (img.get("caption") or "").strip()
        lines.append(f"{i}. [{role}] {caption or '(без подписи)'}")
    return "\n".join(lines) if lines else "(нет изображений)"


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def call_deepseek(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.65,
) -> dict:
    cfg = deepseek_config()
    resp = SESSION.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": model or cfg["translate_model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
        },
        timeout=cfg["timeout"],
    )
    if not resp.ok:
        raise RuntimeError(f"DeepSeek API {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return extract_json(content)


def apply_translation(article: dict, translated: dict) -> dict:
    images = article.get("images", [])
    captions = translated.get("captions_ru") or []
    for i, img in enumerate(images):
        if i < len(captions) and captions[i]:
            img["caption_ru"] = captions[i].strip()

    article["title_ru"] = translated.get("title_ru", "").strip()
    article["excerpt_ru"] = translated.get("excerpt_ru", "").strip()
    slug = translated.get("slug_ru", "").strip()
    if slug:
        article["slug_ru"] = slug

    keys = translated.get("category_keys") or []
    if isinstance(keys, str):
        keys = [keys]
    fallback = article.get("category_ids")
    category_ids, category_keys = resolve_category_ids(keys, fallback_ids=fallback)
    article["category_ids"] = category_ids
    article["category_keys"] = category_keys
    return article


def save_translation_outputs(article_path: Path, article: dict, body_html: str) -> dict:
    out_dir = article_path.parent
    body_path = out_dir / "body_ru.html"
    meta_path = out_dir / "meta.json"

    body_path.write_text(body_html.strip() + "\n", encoding="utf-8")
    meta = {
        "title_ru": article.get("title_ru", ""),
        "excerpt_ru": article.get("excerpt_ru", ""),
        "slug_ru": article.get("slug_ru", ""),
        "category_ids": article.get("category_ids", []),
        "category_keys": article.get("category_keys", []),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    article_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "body_file": str(body_path),
        "meta_file": str(meta_path),
        "article_file": str(article_path),
    }


def translate_article(article_path: Path, skip_filter: bool = False) -> dict:
    article = json.loads(article_path.read_text(encoding="utf-8"))
    source = article.get("source", {})
    title_en = article.get("title_en", "")
    body_en = article.get("content_html_en", "")

    if not skip_filter:
        hit = find_blocked_topic(title_en, html_to_source_text(body_en))
        if hit:
            category, label, keyword = hit
            raise RuntimeError(
                f"Стоп-тема ({label}): «{keyword}» — перевод не запущен. Используйте другую статью."
            )

    prompts = load_prompt_config()
    system = prompts["system"].format(
        categories_list=format_categories_for_prompt(),
    )
    user_msg = prompts["user_template"].format(
        title_en=title_en,
        source_name=source.get("name", ""),
        source_url=source.get("url", ""),
        body_text=html_to_source_text(body_en),
        image_count=len(article.get("images", [])),
        images_list=format_images_list(article.get("images", [])),
    )
    translated = call_deepseek(system, user_msg)

    title_ru = translated.get("title_ru", "").strip()
    excerpt_ru = translated.get("excerpt_ru", "").strip()
    body_ru = translated.get("body_ru_html", "").strip()
    if not title_ru or not excerpt_ru or not body_ru:
        raise RuntimeError("DeepSeek вернул неполный ответ (нужны title_ru, excerpt_ru, body_ru_html)")

    if not skip_filter:
        ensure_allowed(title_ru, body_ru, excerpt_ru, title_en, body_en)

    article = apply_translation(article, translated)
    paths = save_translation_outputs(article_path, article, body_ru)

    return {
        "title_ru": title_ru,
        "excerpt_ru": excerpt_ru,
        "slug_ru": article.get("slug_ru", ""),
        "category_ids": article.get("category_ids", []),
        "category_names": category_names_for_ids(article.get("category_ids", [])),
        "category_keys": article.get("category_keys", []),
        "model": deepseek_config()["translate_model"],
        **paths,
    }


def categorize_article(article_path: Path) -> dict:
    """Assign WordPress categories by article content (without retranslation)."""
    from src.translate import deepseek_config, html_to_source_text

    article = json.loads(article_path.read_text(encoding="utf-8"))
    body_path = article_path.parent / "body_ru.html"

    title = article.get("title_ru") or article.get("title_en", "")
    if body_path.exists():
        text = body_path.read_text(encoding="utf-8")
        if text.strip().startswith("<"):
            text = html_to_source_text(text)
    else:
        text = html_to_source_text(article.get("content_html_en", ""))

    excerpt = article.get("excerpt_ru", "")
    sample = f"{excerpt}\n\n{text}".strip()

    category_ids, category_keys = categorize_with_deepseek(title, sample)
    article["category_ids"] = category_ids
    article["category_keys"] = category_keys

    meta_path = article_path.parent / "meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["category_ids"] = category_ids
    meta["category_keys"] = category_keys
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    article_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "category_ids": category_ids,
        "category_names": category_names_for_ids(category_ids),
        "category_keys": category_keys,
        "model": deepseek_config()["categorize_model"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate article via DeepSeek")
    parser.add_argument("--article", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Skip stop-topics filter")
    args = parser.parse_args()

    result = translate_article(args.article, skip_filter=args.force)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
