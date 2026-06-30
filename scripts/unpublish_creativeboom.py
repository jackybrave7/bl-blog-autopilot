"""Move off-topic Creative Boom posts to draft."""

import json
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv(".env")
base = os.environ["WP_URL"].rstrip("/")
auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"].replace(" ", ""))

CREATIVE_BOOM = "creativeboom.com"
TARGET_IDS = {11102, 11240, 11242, 11252, 11255, 11258}


def source_url(content: str) -> str | None:
    m = re.search(r'href="([^"]+)"[^>]*rel="nofollow', content)
    return m.group(1) if m else None


page = 1
found: list[dict] = []
while True:
    r = requests.get(
        f"{base}/wp-json/wp/v2/posts",
        params={"per_page": 100, "page": page, "status": "publish", "context": "edit"},
        auth=auth,
        timeout=60,
    )
    if r.status_code == 400 or not r.json():
        break
    for post in r.json():
        src = source_url(post["content"]["raw"])
        if post["id"] in TARGET_IDS or (src and CREATIVE_BOOM in src):
            found.append(
                {
                    "id": post["id"],
                    "title": post["title"]["raw"],
                    "source": src,
                }
            )
    page += 1

drafted = []
for post in found:
    resp = requests.post(
        f"{base}/wp-json/wp/v2/posts/{post['id']}",
        auth=auth,
        json={"status": "draft"},
        timeout=60,
    )
    resp.raise_for_status()
    drafted.append(post)

print(json.dumps({"drafted": len(drafted), "posts": drafted}, ensure_ascii=False, indent=2))
