"""WordPress category selection for blog posts."""

from __future__ import annotations

import yaml

from src.lib import CONFIG_DIR, ROOT


def load_category_config() -> dict:
    path = CONFIG_DIR / "categories.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def category_catalog() -> dict[str, dict]:
    return load_category_config().get("categories", {})


def format_categories_for_prompt() -> str:
    lines: list[str] = []
    for key, meta in category_catalog().items():
        lines.append(
            f"- {key} — {meta['name']}: {meta.get('hint', '')}"
        )
    return "\n".join(lines)


def keys_to_ids(keys: list[str]) -> list[int]:
    catalog = category_catalog()
    ids: list[int] = []
    for key in keys:
        key = str(key).strip()
        if not key:
            continue
        meta = catalog.get(key)
        if meta and meta.get("id") not in ids:
            ids.append(int(meta["id"]))
    return ids


def resolve_category_ids(
    keys: list[str] | None,
    fallback_ids: list[int] | None = None,
) -> tuple[list[int], list[str]]:
    """Validate AI keys → WP ids. Returns (ids, resolved_keys)."""
    cfg = load_category_config()
    max_n = int(cfg.get("defaults", {}).get("max_categories", 2))
    fallback_keys = cfg.get("defaults", {}).get("fallback_keys", ["art-history", "artists"])

    resolved_keys: list[str] = []
    for key in keys or []:
        key = str(key).strip()
        if key in category_catalog() and key not in resolved_keys:
            resolved_keys.append(key)
        if len(resolved_keys) >= max_n:
            break

    if not resolved_keys:
        resolved_keys = list(fallback_keys)[:max_n]

    ids = keys_to_ids(resolved_keys)
    if not ids and fallback_ids:
        return list(fallback_ids)[:max_n], resolved_keys
    return ids, resolved_keys


def category_names_for_ids(ids: list[int]) -> list[str]:
    id_to_name = {int(m["id"]): m["name"] for m in category_catalog().values()}
    return [id_to_name[i] for i in ids if i in id_to_name]


def categorize_with_deepseek(title: str, text: str) -> tuple[list[int], list[str]]:
    """Pick categories by article meaning (lightweight DeepSeek call)."""
    from src.translate import call_deepseek, deepseek_config

    system = (
        "Ты классифицируешь статьи блога о визуальных искусствах.\n"
        "Верни JSON: {{\"category_keys\": [\"key1\"]}} — 1–2 ключа из списка.\n"
        "Ориентируйся на содержание, не на источник.\n\n"
        f"Доступные темы:\n{format_categories_for_prompt()}"
    )
    user = f"Заголовок: {title}\n\nТекст:\n{text[:4000]}"
    result = call_deepseek(system, user)
    keys = result.get("category_keys") or []
    if isinstance(keys, str):
        keys = [keys]
    return resolve_category_ids(keys)

