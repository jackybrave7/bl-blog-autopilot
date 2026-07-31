#!/usr/bin/env python3
"""Apply manual translation when DeepSeek API is unavailable."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.content_filter import ensure_allowed
from src.content_focus import ensure_focus_allowed
from src.translate import apply_translation, html_to_source_text, save_translation_outputs


def main() -> None:
    article_path = Path(sys.argv[1])
    body_path = article_path.parent / "body_ru.html"
    article = json.loads(article_path.read_text(encoding="utf-8"))
    body_ru = body_path.read_text(encoding="utf-8")

    translated = {
        "title_ru": "ИИ для поиска картин, украденных нацистами: как работает новая база провенанса",
        "excerpt_ru": (
            "Профессора бизнес-школы Университета Санта-Клары запустили чат-бот "
            "с доступом к базе из 40 тысяч записей о произведениях, изъятых в годы оккупации. "
            "Разбираем, что умеет инструмент и где он пока даёт сбой."
        ),
        "slug_ru": "ii-poisk-kartin-ukradennyh-nacistami-baza-provenansa",
        "category_keys": ["art-history", "technics"],
        "captions_ru": [
            "Архив Jeu de Paume в Париже — один из ключевых источников данных о реквизированном искусстве",
        ],
    }

    title_ru = translated["title_ru"]
    excerpt_ru = translated["excerpt_ru"]
    title_en = article.get("title_en", "")
    body_en = article.get("content_html_en", "")

    ensure_allowed(title_ru, body_ru, excerpt_ru, title_en, body_en)
    ensure_focus_allowed(title_en, html_to_source_text(body_en), title_ru, body_ru)

    # Trim ARTnews lazyload placeholder (not a real illustration).
    images = [
        img
        for img in article.get("images", [])
        if "lazyload-fallback" not in img.get("source_url", "")
    ]
    article["images"] = images

    article = apply_translation(article, translated)
    paths = save_translation_outputs(article_path, article, body_ru)
    print(json.dumps({"ok": True, **paths}, ensure_ascii=False))


if __name__ == "__main__":
    main()
