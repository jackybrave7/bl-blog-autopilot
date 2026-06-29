"""Probe candidate RSS feeds."""
import feedparser
import requests

CANDIDATES = [
    ("artribune", "https://www.artribune.com/feed/"),
    ("finestresullarte", "https://www.finestresullarte.info/feed/"),
    ("exibart", "https://www.exibart.com/feed/"),
    ("floornature", "https://www.floornature.com/feed/"),
    ("artfridge", "https://www.artfridgeonline.com/feed/"),
    ("mymodernmet", "https://mymodernmet.com/feed/"),
    ("scene360", "https://www.scene360.com/feed/"),
    ("designmadeinjapan", "https://designmadeinjapan.com/feed/"),
    ("japan-forward-culture", "https://japan-forward.com/category/culture/feed/"),
    ("tokyoweekender", "https://www.tokyoweekender.com/feed/"),
    ("koreaherald-culture", "https://www.koreaherald.com/rss/kh_Culture"),
    ("hypebeast-kr", "https://hypebeast.kr/feed"),
    ("designfaves", "https://www.designfaves.com/feed"),
    ("designweek", "https://www.designweek.co.uk/feed/"),
    ("grafik-magazine", "https://www.grafik.net/feed/"),
    ("itsnicethat", "https://www.itsnicethat.com/rss"),
    ("paris-art", "https://www.paris-art.com/feed/"),
    ("amuse-iama", "https://amuse-iama.com/feed/"),
    ("artnews", "https://www.artnews.com/feed/"),
    ("artdaily", "https://artdaily.com/rss.xml"),
    ("artfixdaily", "https://www.artfixdaily.com/rss.xml"),
    ("artlyst", "https://www.artlyst.com/feed/"),
    ("contemporaryartdaily", "https://www.contemporaryartdaily.com/feed"),
    ("artasiapacific", "https://www.artasiapacific.com/rss"),
    ("koreanartistproject", "https://www.koreanartistproject.com/feed/"),
]

for name, url in CANDIDATES:
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "BLBlogAutopilot/1.0"})
        ok = r.status_code == 200
        feed = feedparser.parse(r.content) if ok else None
        n = len(feed.entries) if feed else 0
        title = (feed.feed.get("title") or "")[:50] if feed else ""
        print(f"{name:22} {r.status_code} entries={n:3} {title}")
    except Exception as e:
        print(f"{name:22} ERR {e}")
