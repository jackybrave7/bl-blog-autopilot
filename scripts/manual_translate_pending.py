#!/usr/bin/env python3
"""Apply manual translation to a pending article (fallback when DeepSeek API is down)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.translate import apply_translation, save_translation_outputs

ARTICLE_PATH = Path("data/pending/20260819_180253/article.json")

TRANSLATED = {
    "title_ru": "Метал-группа Demon Hunter против Netflix: спор вокруг анимационного «KPop Demon Hunters»",
    "excerpt_ru": (
        "Группа Demon Hunter подала в суд на Netflix и AEG: название хита анимационной франшизы "
        "пересекается с торговой маркой музыкантов. Разбираем, почему для художника важен не только "
        "текст логотипа, но и визуальный бренд проекта."
    ),
    "slug_ru": "demon-hunter-netflix-kpop-demon-hunters",
    "category_keys": ["illustration", "artists"],
    "captions_ru": [
        "Промо-арт анимационного фильма KPop Demon Hunters",
        "Визуальный стиль франшизы KPop Demon Hunters",
        "Продолжение франшизы — KPop Demon Hunters 2",
        "Афиша и графика тура KPop Demon Hunters",
    ],
}

# Keep only hero + three inline KPop images (drop unrelated sidebar assets).
KEEP_FILENAMES = {"img_00.jpg", "img_01.jpg", "img_02.jpg", "img_03.jpg"}


def main() -> None:
    article_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ARTICLE_PATH
    article = json.loads(article_path.read_text(encoding="utf-8"))
    article["images"] = [img for img in article["images"] if img.get("filename") in KEEP_FILENAMES]
    article = apply_translation(article, TRANSLATED)
    body = (article_path.parent / "body_ru.html").read_text(encoding="utf-8")
    paths = save_translation_outputs(article_path, article, body)
    print(json.dumps({"ok": True, **paths}, ensure_ascii=False))


if __name__ == "__main__":
    main()
