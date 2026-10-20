#!/usr/bin/env python3
"""Fetch the latest GTA VI news from public RSS feeds and update VI/news.json.

Runs daily from GitHub Actions. Standard library only.
Keeps a rolling archive (newest first); the site shows the newest 3.
"""
import html, json, re, sys, urllib.request, email.utils
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent.parent / "VI" / "news.json"
KEEP = 300  # older articles stay readable on news.html (archive)
PICK_PER_RUN = 3
MATCH = re.compile(r"\b(GTA\s?(6|VI)|Grand Theft Auto\s?(6|VI))\b", re.I)
FEEDS = [
    ("Push Square", "https://www.pushsquare.com/feeds/latest"),
    ("VGC", "https://www.videogameschronicle.com/feed/"),
    ("Eurogamer", "https://www.eurogamer.net/feed/news"),
    ("GameSpot", "https://www.gamespot.com/feeds/game-news"),
    ("PC Gamer", "https://www.pcgamer.com/rss/"),
    ("Pure Xbox", "https://www.purexbox.com/feeds/latest"),
    (None, "https://news.google.com/rss/search?q=%22GTA+6%22+OR+%22Grand+Theft+Auto+VI%22+when:2d&hl=en-US&gl=US&ceid=US:en"),
]
UA = {"User-Agent": "Mozilla/5.0 (compatible; LeonidaLogBot/1.0; +https://github.com/zuilopez/afterrock)"}
NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/"}


def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean(text, limit=230):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


def slug(title, date):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")
    return f"{s}-{date[:10]}"


def to_iso(raw):
    try:
        return email.utils.parsedate_to_datetime(raw).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def image_of(item, desc_html):
    for tag in ("media:content", "media:thumbnail"):
        el = item.find(tag, NS)
        if el is not None and el.get("url"):
            return el.get("url")
    enc = item.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image") and enc.get("url"):
        return enc.get("url")
    m = re.search(r'<img[^>]+src="([^"]+)"', desc_html or "")
    return m.group(1) if m else ""


def og_image(url):
    try:
        page = get(url, timeout=10)[:300000].decode("utf-8", "ignore")
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', page)
        return html.unescape(m.group(1)) if m else ""
    except Exception:
        return ""


def parse(source, xml_bytes):
    out = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = clean(item.findtext("title"), 200)
        if not MATCH.search(title):
            continue
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or item.findtext("content:encoded", namespaces=NS) or ""
        src = source
        if src is None:  # Google News: "Headline - Publisher"
            s_el = item.find("source")
            src = (s_el.text if s_el is not None else "") or "Google News"
            title = re.sub(r"\s+-\s+[^-]+$", "", title)
            desc = ""
        date = to_iso(item.findtext("pubDate") or "")
        out.append({
            "id": slug(title, date), "title": title, "source": src.strip(), "url": link,
            "date": date, "image": image_of(item, desc), "summary": clean(desc),
        })
    return out


def key(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())[:70]


def main():
    data = {"updated": "", "items": []}
    if OUT.exists():
        data = json.loads(OUT.read_text("utf-8"))
    seen = {key(i["title"]) for i in data["items"]} | {i["url"] for i in data["items"]}
    found = []
    for source, url in FEEDS:
        try:
            found += parse(source, get(url))
        except Exception as e:
            print(f"skip {url}: {e}", file=sys.stderr)
    found.sort(key=lambda i: i["date"], reverse=True)
    fresh = []
    for it in found:
        if it["url"] in seen or key(it["title"]) in seen:
            continue
        seen.add(it["url"]); seen.add(key(it["title"]))
        if not it["image"] and "news.google.com" not in it["url"]:
            it["image"] = og_image(it["url"])
        fresh.append(it)
        if len(fresh) >= PICK_PER_RUN:
            break
    print(f"new items: {len(fresh)}")
    if not fresh:
        return
    items = sorted(fresh + data["items"], key=lambda i: i["date"], reverse=True)[:KEEP]
    data = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
