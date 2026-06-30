# Morning News Podcast Generator

A self-hosted, multi-user service that builds one short (1.5–3 minute) personalized
news podcast every day and exposes it as an RSS feed you can add to any podcast app.
Designed to run in a single Docker container on an Unraid NAS.

## What it does

Every day at a time you choose, it:

1. Gathers **local news** (auto-generated Google News feed for your area, plus any RSS
   feeds you add), **today's weather**, **today's calendar events**, and your **private
   messages**.
2. Uses an LLM (via OpenRouter) to filter stories against your preferences (e.g. "no war
   or politics"), then writes a natural-sounding spoken script.
3. Synthesizes lifelike speech with **ElevenLabs**, prepends your static intro music, appends optional outro music, and
   normalizes loudness with ffmpeg.
4. Publishes the episode to an **RSS feed** with show notes linking to each source article.

### Key features

- **Multi-user**: simple login per person. One shared daily episode/feed.
- **Private messages**: queue a note that's read aloud once in the next episode. Your
  partner can't see your pending messages — they're a surprise. Each is used once then
  resolved.
- **Your sources, your rules**: add RSS feeds and exclude topics you don't want to hear.
- **Tiered article extraction**: plain fetch + trafilatura, falling back to the Zyte API
  for paywalled/JS-heavy pages, then the feed summary. Long articles are summarized to
  control cost.
- **Calendar + weather**: CalDAV / public `.ics` URL, and free Open-Meteo weather.

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env: set SESSION_SECRET, ELEVENLABS_API_KEY, OPENROUTER_API_KEY,
# and BOOTSTRAP_USERNAME / BOOTSTRAP_PASSWORD.

docker compose up -d --build
```

Open `http://<host>:8080`, log in with the bootstrap credentials, then go to **Settings**
to set your location, schedule, voice, and sources. Upload intro and outro `.mp3` files if you'd like.
Copy the feed URL from the dashboard into your podcast app.

Database, episodes, and uploaded audio are stored in a Docker named volume (`morning-news-data`)
that survives image rebuilds and container recreation. To use a host directory instead (common on
Unraid), copy `docker-compose.override.example.yml` to `docker-compose.override.yml`, set your
host path, and redeploy.

If you previously used the old `./data` bind mount, copy that folder into the volume once:

```bash
docker run --rm \
  -v morning-news-data:/data \
  -v "$(pwd)/data:/backup:ro" \
  alpine sh -c 'cp -a /backup/. /data/'
```

### Generate `SESSION_SECRET`

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Running on Unraid

1. Build and push the image (`npm run unraid:push`) or build locally on the NAS.
2. Create a container from `morning-news:latest`.
3. **Map a host path to `/data`** — this is required. The database, episodes, and intro/outro
   mp3 files live here. Without this mapping, each container recreate starts with an empty database.
   A typical path is `/mnt/user/appdata/morning-news`.
4. Map a host port to container port `8080`.
5. Set the environment variables from `.env.example`. Optionally set `BASE_URL` if you
   need a fixed canonical URL for podcast feed links (otherwise URLs are derived from
   however clients reach the server).

When updating to a new image, keep the same `/data` host mapping. Unraid's "Apply" on an
existing container preserves volume mappings; if you recreate the container from scratch,
re-add the host path before starting it.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# CSS (Tailwind v4 — rebuild after editing templates or assets/input.css)
npm install
npm run build:css   # or: npm run watch:css

export DATA_DIR=./data
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export BOOTSTRAP_USERNAME=admin BOOTSTRAP_PASSWORD=admin
export ELEVENLABS_API_KEY=... OPENROUTER_API_KEY=...

uvicorn app.main:app --reload --port 8080
```

`ffmpeg` must be installed locally for audio assembly (`brew install ffmpeg` /
`apt install ffmpeg`).

## Configuration reference

| Env var | Required | Purpose |
| --- | --- | --- |
| `BASE_URL` | optional | Override public URL in RSS enclosures; otherwise derived per request |
| `SESSION_SECRET` | yes | Signs login session cookies |
| `ELEVENLABS_API_KEY` | for audio | Text-to-speech |
| `OPENROUTER_API_KEY` | for scripts | Story selection + script writing |
| `ZYTE_API_KEY` | optional | Article-fetch fallback |
| `NEWSDATA_API_KEY` | optional | Finer-grained local news |
| `FINNHUB_API_KEY` | for stock watch | 24-hour quote changes for your watchlist |
| `BOOTSTRAP_USERNAME` / `BOOTSTRAP_PASSWORD` | first run | Creates the initial user |
| `DATA_DIR` | optional | Defaults to `/data` in Docker |

Everything else (schedule, location, voice, sources, preferences, podcast metadata) is
edited from the web UI and stored in the database.

## Notes

- The feed and audio URLs carry an unguessable token so podcast apps can fetch without a
  login. Keep the feed URL private.
- ElevenLabs `eleven_v3` gives the most realistic delivery; switch to
  `eleven_multilingual_v2` in Settings if your plan doesn't include it.
