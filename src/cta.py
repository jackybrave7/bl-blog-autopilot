"""CTA-баннер для постов блога Bratec Lis School."""

from __future__ import annotations

import os
import re


def build_cta_html() -> str:
    custom = os.environ.get("CTA_HTML", "").strip()
    if custom and custom != "default":
        return custom
    return """
<div class="bl-cta-banner" style="background:linear-gradient(135deg,#2a1a22 0%,#1c1016 100%);border-radius:14px;padding:36px 28px;margin:40px 0;text-align:center;border:1px solid #3d2a34;">
  <p style="color:#d9a441;font-size:13px;letter-spacing:0.14em;text-transform:uppercase;margin:0 0 14px;font-weight:600;">Bratec Lis School · с 2012 года</p>
  <p style="color:#f4ece1;font-size:22px;line-height:1.35;margin:0 0 12px;font-weight:700;">Школа, где художники растут</p>
  <p style="color:#c4b2a4;font-size:16px;line-height:1.55;margin:0 0 8px;max-width:540px;margin-left:auto;margin-right:auto;">Иллюстрация, графика, живопись, акварель, крафт — в живом Zoom с практикующими мастерами из&nbsp;18&nbsp;стран. Маленькие группы: преподаватель разбирает каждую работу, а не читает лекцию в записи.</p>
  <p style="color:#a89890;font-size:14px;line-height:1.5;margin:0 0 26px;max-width:480px;margin-left:auto;margin-right:auto;">Занятия по вечерам и в выходные — можно совмещать с работой. 5&nbsp;000+ учеников за 12 лет.</p>
  <a href="https://www.bl-school.com/" style="display:inline-block;background:#d9a441;color:#1c1016;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px;">Выбрать курс →</a>
</div>
""".strip()


def has_cta_banner(content: str) -> bool:
    return "bl-cta-banner" in content


_SOURCE_BEFORE = re.compile(
    r"<hr[^>]*>\s*<p[^>]*>.*?Источник",
    re.IGNORECASE | re.DOTALL,
)


def inject_cta_html(content: str, cta: str | None = None) -> str:
    """Insert CTA before source footer or at end of post. Idempotent."""
    if has_cta_banner(content):
        return content
    block = (cta or build_cta_html()).strip()
    match = _SOURCE_BEFORE.search(content)
    if match:
        before = content[: match.start()].rstrip()
        after = content[match.start() :].lstrip()
        return f"{before}\n\n{block}\n\n{after}"
    return f"{content.rstrip()}\n\n{block}\n"
