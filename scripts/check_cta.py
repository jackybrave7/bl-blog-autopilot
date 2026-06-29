import requests
from src.lib import wp_config

wp = wp_config()
page = 1
total = 0
with_cta = 0
without = []
while True:
    r = requests.get(
        f"{wp['url']}/wp-json/wp/v2/posts",
        params={"per_page": 100, "page": page, "status": "publish", "_fields": "id,title,content,status"},
        auth=(wp["user"], wp["password"]),
        timeout=60,
    )
    r.raise_for_status()
    posts = r.json()
    if not posts:
        break
    for p in posts:
        total += 1
        if "bl-cta-banner" in p["content"]["rendered"]:
            with_cta += 1
        else:
            without.append((p["id"], p["status"], p["title"]["rendered"][:60]))
    page += 1
    total_pages = int(r.headers.get("X-WP-TotalPages", page))
    if page >= total_pages:
        break

print(f"total={total} with_cta={with_cta} without={len(without)}")
for row in without[:15]:
    print(row)
if len(without) > 15:
    print(f"... and {len(without) - 15} more")
