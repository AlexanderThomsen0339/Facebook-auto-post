# Facebook auto post

AI-agent (Gemini) der laver indhold til en Facebook-side og poster det via Meta Graph API – med godkendelse før hvert opslag.

- `agent.py` – agenten. Finder emne, researcher med Google Search, skriver opslaget og spørger dig før det postes.
- `fb_post.py` – værktøjet der poster (kan også bruges alene).
- `page_profile.md` – hvad siden handler om, emner, tone og format. Agenten holder sig inden for den.
- `medium_sync.py` – henter dine artikler fra Medium (RSS) ned i `articles/`. Agenten kører det selv ved start; kan også køres alene med `python medium_sync.py`. Kræver `MEDIUM_USERNAME` i `.env`.
- `articles/` – dine egne artikler som `.md`. Agenten bygger opslag på dem. Tilføj nye artikler her (første linje `# Titel`, derefter `udgivet:` og evt. `url:` til Medium-linket).

## Agenten

```
python agent.py                    # agenten finder selv et emne
python agent.py "Tulipanmanien"    # du giver emnet
python agent.py --dry-run          # kun udkast, intet postes
```

Ved hvert udkast svarer du `j` (post), `n` (drop) eller skriver rettelser, så laver agenten et nyt udkast.

Kræver `GEMINI_API_KEY` i `.env` (hent den på https://aistudio.google.com/apikey).

## Opsætning

1. `pip install -r requirements.txt`
2. Kopiér `.env.example` til `.env` og udfyld værdierne.
   - `FB_PAGE_ID` / `FB_PAGE_TOKEN`: sidens id og Page access token (fra Graph API Explorer)
   - `FB_APP_ID` / `FB_APP_SECRET`: fra App settings → Basic (kun til token-udveksling)
3. Appen skal have use casen **Manage everything on your Page** med `pages_show_list`, `pages_read_engagement` og `pages_manage_posts`.

## Permanent Page token

```
python fb_post.py --get-token <kortlivet user token>
```
Kopiér tokenet for din side ind i `.env` som `FB_PAGE_TOKEN`.

## fb_post.py alene

```
python fb_post.py "Hej fra Python!"
python fb_post.py "Se vores side" --link https://example.com
python fb_post.py "Nyt billede" --photo billede.jpg
python fb_post.py "Planlagt" --schedule "2026-11-10 09:00"
```

> `.env` er i `.gitignore` – commit aldrig dine tokens.
