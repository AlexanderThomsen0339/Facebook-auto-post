# Facebook auto post

Python-script der poster på en Facebook-side via Meta Graph API (tekst, links, billeder og planlagte opslag).

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

## Brug

```
python fb_post.py "Hej fra Python!"
python fb_post.py "Se vores side" --link https://example.com
python fb_post.py "Nyt billede" --photo billede.jpg
python fb_post.py "Planlagt" --schedule "2026-11-10 09:00"
```

> `.env` er i `.gitignore` – commit aldrig dine tokens.
