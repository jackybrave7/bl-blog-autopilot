"""Apply a manual translation dict to a pending article (when DeepSeek is unavailable)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.content_filter import ensure_allowed
from src.translate import apply_translation, save_translation_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--article", required=True, type=Path)
    parser.add_argument("--translation", required=True, type=Path)
    args = parser.parse_args()

    article = json.loads(args.article.read_text(encoding="utf-8"))
    translated = json.loads(args.translation.read_text(encoding="utf-8"))
    body_path = args.article.parent / "body_ru.html"

    if body_path.exists():
        body_ru = body_path.read_text(encoding="utf-8")
    else:
        body_ru = translated.get("body_ru_html", "").strip()

    title_ru = translated.get("title_ru", "").strip()
    excerpt_ru = translated.get("excerpt_ru", "").strip()
    if not title_ru or not excerpt_ru or not body_ru:
        raise SystemExit("Нужны title_ru, excerpt_ru и body_ru.html")

    ensure_allowed(title_ru, body_ru, excerpt_ru)

    article = apply_translation(article, translated)
    paths = save_translation_outputs(args.article, article, body_ru)
    print(json.dumps({"ok": True, **paths}, ensure_ascii=False))


if __name__ == "__main__":
    main()
