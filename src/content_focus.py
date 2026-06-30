"""Score and filter articles by editorial focus (illustration, painting, craft)."""

from __future__ import annotations

from functools import lru_cache

import yaml

from src.content_filter import _normalize
from src.lib import CONFIG_DIR


class ContentFocusError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@lru_cache(maxsize=1)
def load_focus_config() -> dict:
    with open(CONFIG_DIR / "content_focus.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _keywords(name: str) -> list[str]:
    return [k.lower().replace("ё", "е") for k in load_focus_config().get(name, [])]


def is_source_blocked(source_id: str) -> bool:
    return source_id in set(load_focus_config().get("blocked_source_ids", []))


def is_url_blocked(url: str) -> str | None:
    lower = url.lower()
    for pattern in load_focus_config().get("blocked_url_patterns", []):
        if pattern.lower() in lower:
            return pattern
    return None


def score_text(*texts: str) -> tuple[int, str | None]:
    """Return (score, skip_reason). skip_reason → mark_skipped / reject publish."""
    blob = _normalize(" ".join(t for t in texts if t))
    if not blob:
        return 0, "пустой текст"

    for keyword in _keywords("skip_keywords"):
        if keyword in blob:
            return -99, f"не по теме блога: «{keyword}»"

    preferred_hits = [kw for kw in _keywords("preferred_keywords") if kw in blob]
    deprioritize_hits = [kw for kw in _keywords("deprioritize_keywords") if kw in blob]

    score = len(preferred_hits) * 3 - len(deprioritize_hits) * 2

    if deprioritize_hits and not preferred_hits:
        return score, f"тренды/маркетинг без практики художника: «{deprioritize_hits[0]}»"

    if load_focus_config().get("require_preferred", True) and not preferred_hits:
        return score, "нет темы иллюстрации, живописи или техники"

    min_score = int(load_focus_config().get("min_score", 1))
    if score < min_score:
        return score, f"слабое совпадение с тематикой (score={score})"

    return score, None


def ensure_focus_allowed(*texts: str) -> None:
    _, skip_reason = score_text(*texts)
    if skip_reason:
        raise ContentFocusError(skip_reason)


def check_url_allowed(url: str) -> str | None:
    blocked = is_url_blocked(url)
    if blocked:
        return f"заблокированный URL: «{blocked}»"
    _, skip_reason = score_text(url)
    return skip_reason


def entry_preview_text(entry: dict) -> str:
    parts = [
        entry.get("title", ""),
        entry.get("summary", ""),
        entry.get("description", ""),
    ]
    tags = entry.get("tags") or entry.get("category") or []
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    elif tags:
        parts.append(str(tags))
    return " ".join(parts)
