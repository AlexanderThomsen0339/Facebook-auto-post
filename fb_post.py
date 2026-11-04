"""
fb_post.py – Post automatisk til en Facebook-side via Graph API.

Opsætning:
    pip install requests python-dotenv

Lav en .env-fil ved siden af scriptet:
    FB_PAGE_ID=123456789012345
    FB_PAGE_TOKEN=EAAG...          # Page access token (helst long-lived, se get_long_lived_page_token)
    FB_APP_ID=...                  # kun nødvendig til token-udveksling
    FB_APP_SECRET=...              # kun nødvendig til token-udveksling

Eksempler:
    python fb_post.py "Hej fra Python!"
    python fb_post.py "Se vores nye side" --link https://example.com
    python fb_post.py "Nyt billede" --photo billede.jpg
    python fb_post.py "Planlagt opslag" --schedule "2026-11-10 09:00"
    python fb_post.py --get-token        (du bliver spurgt om dit user token)
"""

import argparse
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

API_VERSION = "v25.0"  # Tjek seneste version på developers.facebook.com
GRAPH = f"https://graph.facebook.com/{API_VERSION}"

PAGE_ID = os.getenv("FB_PAGE_ID")
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")


def _check(resp: requests.Response) -> dict:
    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"Graph API-fejl {err.get('code')}: {err.get('message')}")
    return data


def post_text(message: str, link: str | None = None, schedule: datetime | None = None) -> dict:
    """Tekstopslag (evt. med link). Med schedule bliver opslaget planlagt."""
    payload = {"message": message, "access_token": PAGE_TOKEN}
    if link:
        payload["link"] = link
    if schedule:
        # Skal være mellem 10 minutter og 30 dage ude i fremtiden
        payload["published"] = "false"
        payload["scheduled_publish_time"] = int(schedule.timestamp())
    return _check(requests.post(f"{GRAPH}/{PAGE_ID}/feed", data=payload, timeout=30))


def post_photo(message: str, photo_path: str, schedule: datetime | None = None) -> dict:
    """Opslag med billede fra en lokal fil."""
    payload = {"caption": message, "access_token": PAGE_TOKEN}
    if schedule:
        payload["published"] = "false"
        payload["scheduled_publish_time"] = int(schedule.timestamp())
    with open(photo_path, "rb") as f:
        resp = requests.post(
            f"{GRAPH}/{PAGE_ID}/photos", data=payload, files={"source": f}, timeout=60
        )
    return _check(resp)


def get_recent_posts(limit: int = 15) -> list[dict]:
    """Hent sidens seneste opslag (tekst + tidspunkt)."""
    data = _check(requests.get(f"{GRAPH}/{PAGE_ID}/posts", params={
        "fields": "message,created_time,permalink_url",
        "limit": limit,
        "access_token": PAGE_TOKEN,
    }, timeout=30))
    return data.get("data", [])


def get_long_lived_page_token(short_user_token: str) -> str:
    """
    Byt et kortlivet user token (fra Graph API Explorer) til et Page token,
    der ikke udløber. Kør én gang og gem resultatet i .env som FB_PAGE_TOKEN.
    """
    app_id, app_secret = os.getenv("FB_APP_ID"), os.getenv("FB_APP_SECRET")
    if not (app_id and app_secret):
        sys.exit("Sæt FB_APP_ID og FB_APP_SECRET i .env først.")

    # 1) Kortlivet user token -> long-lived user token (~60 dage)
    long_user = _check(requests.get(f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_user_token,
    }, timeout=30))["access_token"]

    # 2) Hent Page tokens – afledt af et long-lived user token udløber de ikke
    pages = _check(requests.get(f"{GRAPH}/me/accounts",
                                params={"access_token": long_user}, timeout=30))["data"]
    for p in pages:
        print(f"{p['name']}  (id={p['id']})\n  token: {p['access_token']}\n")
    match = next((p for p in pages if p["id"] == PAGE_ID), None)
    return match["access_token"] if match else ""


def main():
    ap = argparse.ArgumentParser(description="Post til en Facebook-side")
    ap.add_argument("message", nargs="?", help="Teksten til opslaget")
    ap.add_argument("--link", help="URL der skal deles")
    ap.add_argument("--photo", help="Sti til et billede")
    ap.add_argument("--schedule", help='Planlæg opslag, fx "2026-11-10 09:00" (lokal tid)')
    ap.add_argument("--get-token", metavar="USER_TOKEN", nargs="?", const="",
                    help="Byt kortlivet user token til permanent Page token "
                         "(udelad værdien for at blive spurgt)")
    args = ap.parse_args()

    if args.get_token is not None:
        token = args.get_token or input("Indsæt dit user token (starter med EAA): ")
        get_long_lived_page_token(token.strip().strip('"').strip())
        return

    if not (PAGE_ID and PAGE_TOKEN):
        sys.exit("Sæt FB_PAGE_ID og FB_PAGE_TOKEN i .env")
    if not args.message:
        ap.error("Du skal angive en besked")

    when = datetime.strptime(args.schedule, "%Y-%m-%d %H:%M") if args.schedule else None

    if args.photo:
        result = post_photo(args.message, args.photo, when)
    else:
        result = post_text(args.message, args.link, when)

    post_id = result.get("post_id") or result.get("id")
    print(f"✅ {'Planlagt' if when else 'Postet'}: https://www.facebook.com/{post_id}")


if __name__ == "__main__":
    main()
