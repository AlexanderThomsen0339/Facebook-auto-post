"""
medium_sync.py – Henter dine artikler fra Medium (via RSS) ned i articles/.

Kræver i .env:
    MEDIUM_USERNAME=ditbrugernavn        # det efter @ i medium.com/@ditbrugernavn

Brug:
    python medium_sync.py                # hent nye artikler

Bemærk: Mediums RSS-feed indeholder kun dine ~10 seneste artikler.
Artikler bag Mediums betalingsmur kan komme med som et uddrag – de markeres
med "delvis: ja", og så researcher agenten resten.
"""

import os
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ARTICLES_DIR = Path(__file__).with_name("articles")
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; facebook-auto-post/1.0)"}


class _HtmlToText(HTMLParser):
    """Gør Mediums HTML til læsbar tekst (afsnit, overskrifter, lister)."""
    BLOCK = {"p", "h1", "h2", "h3", "h4", "blockquote", "figcaption", "pre", "li"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.parts.append("\n\n## ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        t = "".join(self.parts)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n[ \t]+", "\n", t)
        return re.sub(r"\n{3,}", "\n\n", t).strip()


def html_to_text(html: str) -> str:
    p = _HtmlToText()
    p.feed(html)
    return p.text()


def slugify(s: str) -> str:
    s = s.lower()
    for a, b in (("æ", "ae"), ("ø", "oe"), ("å", "aa")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60].rstrip("-") or "artikel"


def _existing_titles() -> dict[str, Path]:
    out = {}
    for f in ARTICLES_DIR.glob("*.md"):
        first = f.read_text(encoding="utf-8").splitlines()[:1]
        if first:
            out[first[0].lstrip("# ").strip().lower()] = f
    return out


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        html = item.findtext(CONTENT_NS) or item.findtext("description") or ""
        pub = item.findtext("pubDate") or ""
        try:
            pub = parsedate_to_datetime(pub).strftime("%b %d, %Y")
        except (TypeError, ValueError):
            pass
        link = (item.findtext("link") or "").split("?")[0]
        text = html_to_text(html)
        partial = ("Continue reading on Medium" in text) or len(text.split()) < 150
        items.append({
            "title": (item.findtext("title") or "Uden titel").strip(),
            "url": link,
            "date": pub,
            "text": text.replace("Continue reading on Medium »", "").strip(),
            "partial": partial,
        })
    return items


def sync(username: str | None = None) -> list[str]:
    """Henter feedet og gemmer nye artikler. Returnerer en liste over ændringer."""
    username = (username or os.getenv("MEDIUM_USERNAME", "")).lstrip("@").strip()
    if not username:
        raise RuntimeError("Sæt MEDIUM_USERNAME i .env")

    resp = requests.get(f"https://medium.com/feed/@{username}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    ARTICLES_DIR.mkdir(exist_ok=True)
    existing = _existing_titles()
    changes = []

    for a in parse_feed(resp.text):
        known = existing.get(a["title"].lower())
        if known:
            # Artiklen findes allerede – udfyld bare url'en, hvis den mangler
            content = known.read_text(encoding="utf-8")
            if re.search(r"^url:\s*$", content, re.M) and a["url"]:
                known.write_text(re.sub(r"^url:\s*$", f"url: {a['url']}", content,
                                        count=1, flags=re.M), encoding="utf-8")
                changes.append(f"url tilføjet: {known.name}")
            continue

        path = ARTICLES_DIR / f"{slugify(a['title'])}.md"
        header = f"# {a['title']}\n\nudgivet: {a['date']}\nurl: {a['url']}\n"
        if a["partial"]:
            header += "delvis: ja (kun uddrag fra Medium – research resten)\n"
        path.write_text(f"{header}\n{a['text']}\n", encoding="utf-8")
        existing[a["title"].lower()] = path
        changes.append(f"ny artikel: {path.name}" + (" (delvis)" if a["partial"] else ""))

    return changes


if __name__ == "__main__":
    result = sync()
    print("\n".join(result) if result else "Ingen nye artikler.")
