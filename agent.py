"""
agent.py – AI-agent (Gemini) der laver indhold til Facebook-siden og poster
via fb_post.py. Du godkender hvert opslag, før det går live.

Brug:
    python agent.py                      # agenten finder selv et emne
    python agent.py "Tulipanmanien"      # du giver emnet
    python agent.py --dry-run            # lav et udkast uden at poste

Kræver i .env:
    GEMINI_API_KEY=...                   # fra aistudio.google.com/apikey
    FB_PAGE_ID / FB_PAGE_TOKEN           # som til fb_post.py
    GEMINI_MODEL=gemini-flash-latest     # valgfri
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

import fb_post

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
PROFILE_PATH = Path(__file__).with_name("page_profile.md")
DRY_RUN = False

client: genai.Client | None = None  # oprettes i main()


# ---------- Værktøjer agenten kan kalde ----------

def get_recent_posts(limit: int = 15) -> str:
    """Henter sidens seneste opslag, så du kan undgå at gentage emner.

    Args:
        limit: Antal opslag der skal hentes (max 50).
    """
    print(f"🔧 Henter de seneste {limit} opslag fra siden...")
    try:
        posts = fb_post.get_recent_posts(min(limit, 50))
    except Exception as e:
        return f"Kunne ikke hente opslag: {e}"
    if not posts:
        return "Siden har ingen tidligere opslag."
    return "\n\n".join(
        f"[{p.get('created_time', '')[:10]}] {p.get('message', '(intet tekstindhold)')[:300]}"
        for p in posts
    )


def research_topic(topic: str) -> str:
    """Researcher et emne med Google Search og returnerer verificerbare fakta
    (årstal, personer, tal) med kilder. Brug altid dette før du skriver et opslag.

    Args:
        topic: Emnet der skal researches, fx "Tulipanmanien i Holland 1637".
    """
    print(f"🔧 Researcher: {topic}")
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=(
                f"Find de vigtigste verificerbare fakta om: {topic}. "
                "Giv årstal, nøglepersoner, konkrete tal og 2-3 overraskende detaljer. "
                "Angiv kilder. Svar kort i punktform."
            ),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        return resp.text or "Ingen resultater."
    except Exception as e:
        return f"Research fejlede: {e}"


def publish_post(message: str, link: str = "") -> str:
    """Viser opslaget for brugeren og poster det på Facebook-siden, hvis brugeren
    godkender. Hvis brugeren skriver rettelser, får du dem tilbage – lav så et
    nyt udkast og kald publish_post igen.

    Args:
        message: Den færdige tekst til opslaget.
        link: Valgfri URL der skal deles med opslaget.
    """
    print("\n" + "=" * 60)
    print(message)
    if link:
        print(f"\n🔗 {link}")
    print("=" * 60)

    if DRY_RUN:
        return "Dry-run: opslaget blev ikke postet. Stop her."

    answer = input("\nPost dette? [j]a / [n]ej / eller skriv rettelser: ").strip()
    if answer.lower() in ("j", "ja", "y", "yes"):
        try:
            result = fb_post.post_text(message, link or None)
        except Exception as e:
            return f"Fejl ved postning: {e}"
        url = f"https://www.facebook.com/{result.get('id')}"
        print(f"✅ Postet: {url}")
        return f"Opslaget er postet: {url}. Opgaven er færdig."
    if answer.lower() in ("n", "nej", "no", ""):
        return "Brugeren afviste opslaget. Stop og post ikke noget."
    return f"Brugeren vil have disse rettelser: {answer}. Lav et nyt udkast og kald publish_post igen."


# ---------- Agenten ----------

def build_system_prompt() -> str:
    profile = PROFILE_PATH.read_text(encoding="utf-8")
    return f"""Du er content-agent for en Facebook-side. Dags dato: {date.today()}.

{profile}

Sådan arbejder du:
1. Kald get_recent_posts for at se hvad der allerede er skrevet.
2. Hvis brugeren ikke har givet et emne, så vælg ét inden for sidens emner,
   som ikke er dækket i de seneste opslag.
3. Kald research_topic for at få fakta. Brug kun fakta fra researchen.
4. Skriv opslaget efter sidens tone og format.
5. Kald publish_post med teksten. Post aldrig uden at kalde publish_post.
6. Følg svaret fra publish_post: ret og prøv igen, eller stop.
Svar til sidst med én kort linje om hvad der skete."""


def run(topic: str | None) -> None:
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            tools=[get_recent_posts, research_topic, publish_post],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=20
            ),
        ),
    )
    task = f"Lav et opslag om: {topic}" if topic else "Find selv et emne og lav et opslag."
    print(f"🤖 Agent starter ({MODEL})...")
    response = chat.send_message(task)
    print(f"\n🤖 {response.text}")


def main():
    global DRY_RUN
    ap = argparse.ArgumentParser(description="AI-agent der laver Facebook-opslag")
    ap.add_argument("topic", nargs="?", help="Valgfrit emne")
    ap.add_argument("--dry-run", action="store_true", help="Lav udkast uden at poste")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        sys.exit("Sæt GEMINI_API_KEY i .env (hent den på aistudio.google.com/apikey)")
    if not (fb_post.PAGE_ID and fb_post.PAGE_TOKEN):
        sys.exit("Sæt FB_PAGE_ID og FB_PAGE_TOKEN i .env")

    global client
    client = genai.Client()  # læser GEMINI_API_KEY fra miljøet
    run(args.topic)


if __name__ == "__main__":
    main()
