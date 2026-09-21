"""Фильтр стоп-тем для статей блога."""

from __future__ import annotations

import html
import re
from functools import lru_cache

import yaml

from src.lib import CONFIG_DIR


class ContentBlockedError(Exception):
    def __init__(self, category: str, label: str, keyword: str) -> None:
        self.category = category
        self.label = label
        self.keyword = keyword
        super().__init__(f"Стоп-тема «{label}»: совпадение «{keyword}»")


@lru_cache(maxsize=1)
def load_stop_topics() -> dict[str, dict]:
    with open(CONFIG_DIR / "stop_topics.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("topics", {})


def _normalize(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def _keyword_matches(kw: str, blob: str) -> bool:
    """Совпадение по слову для латиницы; подстрока для кириллицы и многословных ключей."""
    if not kw:
        return False
    if " " in kw or not re.fullmatch(r"[a-z][a-z-]*", kw):
        return kw in blob
    return re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", blob) is not None


def find_blocked_topic(*texts: str) -> tuple[str, str, str] | None:
    """Возвращает (category_id, label, keyword) или None."""
    blob = _normalize(" ".join(t for t in texts if t))
    if not blob:
        return None
    for category, meta in load_stop_topics().items():
        label = meta.get("label", category)
        for keyword in meta.get("keywords", []):
            kw = keyword.lower().replace("ё", "е")
            if _keyword_matches(kw, blob):
                return category, label, keyword
    return None


def ensure_allowed(*texts: str) -> None:
    hit = find_blocked_topic(*texts)
    if hit:
        category, label, keyword = hit
        raise ContentBlockedError(category, label, keyword)


def is_allowed(*texts: str) -> bool:
    return find_blocked_topic(*texts) is None
