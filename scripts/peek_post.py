import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv(".env")
slug = sys.argv[1] if len(sys.argv) > 1 else "cannes-lions-2026-rezonans-nishi-analogovyj-renessans"
base = os.environ["WP_URL"].rstrip("/")
auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"].replace(" ", ""))
r = requests.get(
    f"{base}/wp-json/wp/v2/posts",
    params={"slug": slug, "context": "edit", "status": "any"},
    auth=auth,
    timeout=30,
)
p = r.json()[0]
print("id", p["id"], "status", p["status"])
print("title", p["title"]["raw"])
content = p["content"]["raw"]
m = re.search(r'href="([^"]+)"[^>]*rel="nofollow', content)
print("source", m.group(1) if m else "?")
