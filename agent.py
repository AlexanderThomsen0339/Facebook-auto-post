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
import threading
import time
from urllib.parse import unquote
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

import fb_post
import medium_sync

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Reservemodeller hvis hovedmodellen er overbelastet (503/429). Kommasepareret.
FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest").split(",") if m.strip()]
# Hvor meget modellen "tænker" før den svarer: low er hurtigst. Sæt tom for modellens standard.
THINKING_LEVEL = os.getenv("GEMINI_THINKING", "low")
PROFILE_PATH = Path(__file__).with_name("page_profile.md")
ARTICLES_DIR = Path(__file__).with_name("articles")
DRY_RUN = False
OUTCOME: str | None = None  # sættes af publish_post – den rigtige status, ikke modellens

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


def sync_medium() -> str:
    """Henter nye artikler fra brugerens Medium-profil ned i artikel-biblioteket.
    Kald dette først, så du arbejder med de nyeste artikler."""
    print("🔧 Henter artikler fra Medium...")
    if not os.getenv("MEDIUM_USERNAME"):
        return "MEDIUM_USERNAME er ikke sat – bruger kun de lokale artikler."
    try:
        changes = medium_sync.sync()
    except Exception as e:
        return f"Kunne ikke hente fra Medium ({e}) – bruger de lokale artikler."
    for c in changes:
        print(f"   {c}")
    return "\n".join(changes) if changes else "Ingen nye artikler på Medium."


def list_articles() -> str:
    """Viser sidens egne artikler (filnavn, titel, dato). Brug dem som primær
    kilde til opslag."""
    print("🔧 Lister artikler...")
    rows = []
    for f in sorted(ARTICLES_DIR.glob("*.md")):
        lines = f.read_text(encoding="utf-8").splitlines()
        title = lines[0].lstrip("# ").strip() if lines else f.stem
        meta = {l.split(":", 1)[0]: l.split(":", 1)[1].strip()
                for l in lines[1:6] if ":" in l}
        rows.append(f"- {f.name}: {title} (udgivet {meta.get('udgivet', '?')})")
    return "\n".join(rows) or "Ingen artikler fundet."


def read_article(filename: str) -> str:
    """Læser hele teksten i én af sidens artikler.

    Args:
        filename: Filnavnet fra list_articles, fx "romerrigets-inflation.md".
    """
    print(f"🔧 Læser artikel: {filename}")
    path = (ARTICLES_DIR / Path(filename).name)
    if not path.exists():
        return f"Artiklen {filename} findes ikke. Brug list_articles."
    return path.read_text(encoding="utf-8")


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


def _hashtags_before_cta(message: str) -> str:
    """Flyt hashtag-linjer op foran en afsluttende "Læs ..."-linje, så opslaget
    slutter med opfordringen lige over link-kortet."""
    lines = message.splitlines()
    tags = [l for l in lines if l.strip() and all(w.startswith("#") for w in l.split())]
    cta_idx = next((i for i, l in enumerate(lines) if l.strip().lower().startswith("læs")), None)
    if not tags or cta_idx is None:
        return message
    if all(lines.index(t) < cta_idx for t in tags):
        return message
    rest = [l for l in lines if l not in tags]
    cta_idx = next(i for i, l in enumerate(rest) if l.strip().lower().startswith("læs"))
    out = rest[:cta_idx] + tags + [""] + rest[cta_idx:]
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def publish_post(message: str, link: str = "") -> str:
    """Viser opslaget for brugeren og poster det på Facebook-siden, hvis brugeren
    godkender. Hvis brugeren skriver rettelser, får du dem tilbage – lav så et
    nyt udkast og kald publish_post igen.

    Args:
        message: Den færdige tekst til opslaget. Skriv IKKE url'en i teksten –
            giv den i link, så viser Facebook den som et kort med billede.
        link: Valgfri URL der skal deles med opslaget.
    """
    if link:
        # Fjern url'en fra teksten (rå eller %-kodet) – Facebook viser den som kort
        for u in {link, unquote(link)}:
            message = message.replace(u, "")
        message = "\n".join(l.rstrip() for l in message.splitlines())
        while "\n\n\n" in message:
            message = message.replace("\n\n\n", "\n\n")
        message = message.strip()
        message = _hashtags_before_cta(message)
    print("\n" + "=" * 60)
    print(message)
    if link:
        print(f"\n🔗 {link}")
    print("=" * 60)

    global OUTCOME
    if DRY_RUN:
        OUTCOME = "🧪 Dry-run: udkastet blev vist, men IKKE postet. Kør uden --dry-run for at poste."
        return "Dry-run: opslaget blev ikke postet. Stop her."

    WAITING_FOR_USER.set()
    try:
        answer = input("\nPost dette? [j]a / [n]ej / eller skriv rettelser: ").strip()
    finally:
        WAITING_FOR_USER.clear()
    if answer.lower() in ("j", "ja", "y", "yes"):
        try:
            result = fb_post.post_text(message, link or None)
        except Exception as e:
            OUTCOME = f"⚠️  Fejl ved postning: {e}"
            return f"Fejl ved postning: {e}"
        url = f"https://www.facebook.com/{result.get('id')}"
        OUTCOME = f"✅ Postet: {url}"
        return f"Opslaget er postet: {url}. Opgaven er færdig."
    if answer.lower() in ("n", "nej", "no", ""):
        OUTCOME = "❌ Du afviste opslaget. Intet blev postet."
        return "Brugeren afviste opslaget. Stop og post ikke noget."
    return f"Brugeren vil have disse rettelser: {answer}. Lav et nyt udkast og kald publish_post igen."


# ---------- Agenten ----------

def build_system_prompt() -> str:
    profile = PROFILE_PATH.read_text(encoding="utf-8")
    return f"""Du er content-agent for en Facebook-side. Dags dato: {date.today()}.

{profile}

Sådan arbejder du:
1. Kald sync_medium og get_recent_posts.
2. Kald list_articles. Sidens egne artikler er din primære kilde.
   - Har brugeren givet et emne: find den artikel der handler om DET emne.
     Findes der ingen artikel om emnet, så byg opslaget på research_topic og
     giv INTET link – link aldrig til en artikel om et andet emne.
   - Ellers: prioritér nye artikler, som siden endnu ikke har lavet opslag om.
     Ellers vælg en artikel og en vinkel der ikke er dækket i de seneste opslag.
     Én artikel kan give mange opslag med forskellige vinkler (et tal, en
     anekdote, en parallel til i dag).
3. Kald read_article og byg opslaget på artiklens indhold.
   Brug kun research_topic hvis artiklen ikke dækker emnet, er markeret
   "delvis", eller et faktum skal tjekkes. Opfind aldrig tal.
4. Skriv opslaget efter sidens tone og format. Hvis artiklen har en url,
   så giv den som link-parameter i publish_post – skriv den ikke i teksten.
   Afslut gerne med en kort opfordring som "Læs hele artiklen 👇".
5. Kald publish_post med teksten. Post aldrig uden at kalde publish_post.
6. Følg svaret fra publish_post: ret og prøv igen, eller stop.
Svar til sidst med én kort linje om hvad der skete."""


WAITING_FOR_USER = threading.Event()  # pauser hjerteslaget mens brugeren svarer


class Heartbeat:
    """Skriver løbende hvor længe vi har ventet, så man kan se agenten lever."""
    def __init__(self, label: str):
        self.label, self._stop = label, threading.Event()

    def __enter__(self):
        self.start = time.time()
        def beat():
            while not self._stop.wait(10):
                if WAITING_FOR_USER.is_set():
                    continue
                print(f"   ⏳ {self.label} ({int(time.time() - self.start)} s)...", flush=True)
        threading.Thread(target=beat, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._stop.set()


def run(topic: str | None) -> None:
    global MODEL
    task = f"Lav et opslag om: {topic}" if topic else "Find selv et emne og lav et opslag."
    for model in [MODEL, *FALLBACK_MODELS]:
        MODEL = model  # research_topic bruger samme model
        try:
            try:
                _run_with_model(model, task, THINKING_LEVEL)
            except errors.ClientError as e:
                # Nogle modeller understøtter ikke thinking_level – prøv uden
                if e.code == 400 and THINKING_LEVEL and "thinking" in str(e).lower():
                    _run_with_model(model, task, "")
                else:
                    raise
            return
        except errors.APIError as e:
            if e.code not in (429, 500, 503, 504):
                raise
            print(f"⚠️  {model} er utilgængelig ({e.code}). Prøver næste model...")
    sys.exit("Alle modeller er overbelastede lige nu. Prøv igen om lidt.")


TOOLS = [sync_medium, get_recent_posts, list_articles, read_article,
         research_topic, publish_post]
MAX_STEPS = 20


def _run_with_model(model: str, task: str, thinking_level: str) -> None:
    chat = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            thinking_config=(types.ThinkingConfig(thinking_level=thinking_level)
                             if thinking_level else None),
            system_instruction=build_system_prompt(),
            tools=TOOLS,
            # Vi kører værktøjerne selv, så vi kan stoppe så snart opslaget er
            # postet/afvist – i stedet for at vente på modellens afsluttende svar.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    tools = {f.__name__: f for f in TOOLS}
    print(f"🤖 Agent starter ({model})...")

    message = task
    for _ in range(MAX_STEPS):
        with Heartbeat("Gemini arbejder"):
            response = chat.send_message(message)
        calls = response.function_calls or []
        if not calls:
            break  # modellen er færdig uden flere værktøjskald

        parts = []
        for call in calls:
            fn = tools.get(call.name)
            try:
                result = fn(**(call.args or {})) if fn else f"Ukendt værktøj: {call.name}"
            except Exception as e:
                result = f"Fejl i {call.name}: {e}"
            parts.append(types.Part.from_function_response(
                name=call.name, response={"result": result}))

        if OUTCOME:
            break  # postet, afvist, dry-run eller fejl – intet mere at vente på
        message = parts

    # Status kommer fra koden – modellens egen opsummering kan være forkert
    print("\n" + (OUTCOME or "⚠️  Agenten nåede ikke frem til et udkast. Intet blev postet."))


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
    # Læser GEMINI_API_KEY fra miljøet. Prøver selv igen ved overbelastning.
    client = genai.Client(http_options=types.HttpOptions(
        timeout=60_000,  # ms – giv op på et kald efter 60 sek.
        retry_options=types.HttpRetryOptions(
            attempts=2, initial_delay=3, max_delay=10,
            http_status_codes=[429, 500, 503, 504],
        )
    ))
    run(args.topic)


if __name__ == "__main__":
    main()
