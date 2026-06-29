import sys

from src.lib import wp_config
import requests

post_id = int(sys.argv[1]) if len(sys.argv) > 1 else 11096
wp = wp_config()
resp = requests.get(
    f"{wp['url']}/wp-json/wp/v2/posts/{post_id}?_fields=content",
    auth=(wp["user"], wp["password"]),
)
p = resp.json()
before = p["content"]["rendered"].split("<!--more-->")[0]
print("img in teaser:", "<img" in before)
print(before[:700])
