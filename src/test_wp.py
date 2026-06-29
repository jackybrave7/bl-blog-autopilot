"""Quick WordPress API auth check."""

from __future__ import annotations

import json
import sys

import requests

from src.lib import wp_config


def main() -> None:
    wp = wp_config()
    resp = requests.get(
        f"{wp['url']}/wp-json/wp/v2/users/me",
        auth=(wp["user"], wp["password"]),
        timeout=20,
    )
    if resp.status_code != 200:
        print(json.dumps({"ok": False, "status": resp.status_code, "body": resp.text[:300]}))
        sys.exit(1)
    user = resp.json()
    print(json.dumps({"ok": True, "user": user.get("slug"), "name": user.get("name")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
