import re
import requests
from src.lib import wp_config

wp = wp_config()
r = requests.get(
    f"{wp['url']}/wp-json/wp/v2/posts/10430",
    params={"context": "edit"},
    auth=(wp["user"], wp["password"]),
)
p = r.json()
raw = p["content"]["raw"]
print("raw len", len(raw))
print("has cta", "bl-cta-banner" in raw)
print("tail:", raw[-400:])
