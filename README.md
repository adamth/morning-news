# Morning News Podcast Generator

A self-hosted, multi-user service that builds one short (1.5–3 minute) personalized
news podcast every day and exposes it as an RSS feed you can add to any podcast app.
Designed to run in a single Docker container on an Unraid NAS.

## What it does

Every day at a time you choose, it:

1. Gathers **local news** (auto-generated Google News feed for your area, plus any RSS
   feeds you add), **today's weather**, **today's calendar events**, and your **private
   messages**.
2. Uses an LLM to filter stories against your preferences (e.g. "no war
   or politics"), then writes a natural-sounding spoken script. Supports OpenRouter,
   OpenAI, Anthropic Claude, or any OpenAI-compatible API.
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

## Running your own instance (Docker)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- Accounts for the services you want (ElevenLabs for audio, plus one LLM provider — added in the web UI after first login)

Optional accounts unlock extra features; add them under **Settings → Connections** when you need them.

### 1. Get the code

```bash
git clone https://github.com/adamth/morning-news.git
cd morning-news
```

Or download and extract a release tarball — you only need the repo root (Dockerfile, `docker-compose.yml`, etc.).

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` in an editor. Docker Compose reads this file automatically when you start the stack.

**Minimum to start the container:**

| Variable | Where to get it | What it does |
| --- | --- | --- |
| `SESSION_SECRET` | Generate locally (see below) | Signs login session cookies and encrypts API keys stored in the database. If you change it, everyone is logged out and saved keys must be re-entered. |
| `BOOTSTRAP_USERNAME` | You choose | Username for the first admin account. Used only when the database has no users yet. |
| `BOOTSTRAP_PASSWORD` | You choose | Password for that first account. Change it after logging in. |

Generate a strong `SESSION_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the output into `.env` as `SESSION_SECRET=...`.

**API keys** (ElevenLabs, OpenRouter, OpenAI, Claude, etc.) are normally added in the web UI under **Settings → Connections** after you log in. They are encrypted and stored in the SQLite database under `/data`. You can still set keys via environment variables if you prefer — env values override saved keys (useful for Docker automation).

**Optional server configuration:**

| Variable | Where to get it | What it does |
| --- | --- | --- |
| `BASE_URL` | Your public URL, e.g. `https://news.example.com` | Forces RSS feed and episode download links to use this URL. Leave unset if you access the app directly; set it when behind a reverse proxy or custom domain so podcast apps get correct audio URLs. |

**Docker-only (Unraid / pre-built image workflows):**

| Variable | Where to get it | What it does |
| --- | --- | --- |
| `DOCKER_IMAGE` | Your Docker Hub repo, e.g. `youruser/morning-news:latest` | Image name for `docker-compose.unraid.yml` and `npm run unraid:push`. Ignored when building locally with `docker compose up --build`. |
| `HOST_PORT` | Host port you want, e.g. `8084` | Maps `HOST_PORT:8080` in `docker-compose.unraid.yml`. Default `8080`. |
| `APP_DATA_DIR` | Host path, e.g. `/mnt/user/appdata/morning-news` | Binds your NAS/appdata folder to `/data` in the Unraid compose file. |

Everything else — schedule, location, voice, RSS sources, topic exclusions, calendar URL, podcast title — is configured in the **web UI** after login and stored in the SQLite database under `/data`.

### 3. Start the container

From the repo root:

```bash
docker compose up -d --build
```

- Builds the image locally (or uses `DOCKER_IMAGE` if you set one and skip `--build`).
- Maps host port **8080** → container **8080** (edit `docker-compose.yml` if 8080 is taken).
- Stores data in the named volume **`morning-news-data`** (database, episodes, uploaded intro/outro/artwork).

Check that it is healthy:

```bash
docker compose ps
docker compose logs -f morning-news
```

The entrypoint refuses to start if `/data` is not a persistent volume mount, so you never accidentally run with ephemeral storage.

**Use a host directory instead of a named volume** (common on NAS / Unraid):

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
# Edit the host path in docker-compose.override.yml, then:
docker compose up -d --build
```

`docker-compose.override.yml` is gitignored; Compose merges it automatically.

If you previously used a `./data` bind mount, copy it into the named volume once:

```bash
docker run --rm \
  -v morning-news-data:/data \
  -v "$(pwd)/data:/backup:ro" \
  alpine sh -c 'cp -a /backup/. /data/'
```

### 4. First login and setup

1. Open `http://<your-host>:8080` (or `http://localhost:8080` on the same machine).
2. Log in with `BOOTSTRAP_USERNAME` / `BOOTSTRAP_PASSWORD`.
3. Go to **Settings → Connections** and add:
   - **ElevenLabs** — required for audio ([get a key](https://elevenlabs.io/app/settings/api-keys))
   - **One script-writing provider** — OpenRouter, OpenAI, Anthropic, or a custom URL ([OpenRouter](https://openrouter.ai/keys) is the easiest way to try many models)
   - Optional: **Finnhub** for stock watch, **Zyte** for difficult news pages
4. Go to **Settings → Advanced** and pick your script-writing provider and model.
5. On **Settings → Basic**, configure location, schedule, sources, and voice.
6. Open **System status** to confirm everything connects.
7. Copy the **RSS feed URL** from the dashboard into your podcast app.

The feed URL includes an unguessable token so podcast apps can download episodes without logging in. Treat it like a password.

### 5. Updates and backups

**Update to the latest code:**

```bash
git pull
docker compose up -d --build
```

**Back up your data:** copy the contents of the `morning-news-data` volume or your bind-mounted host directory. That folder holds `morning_news.db`, `episodes/`, and uploaded media.

### Reverse proxy / HTTPS

If you terminate TLS in front of the container (nginx, Caddy, Traefik, Cloudflare Tunnel):

1. Forward `Host`, `X-Forwarded-Proto`, and `X-Forwarded-For` to the app (the container trusts proxy headers).
2. Set `BASE_URL=https://your-public-hostname` in `.env` so RSS enclosure URLs point at HTTPS.

Then restart: `docker compose up -d`.

## Running on Unraid

Unraid follows the same `.env` setup as [Running your own instance (Docker)](#running-your-own-instance-docker). The difference is how data and images are managed: you keep `docker-compose.unraid.yml` and `.env` in appdata and pull pre-built images instead of building on the NAS.

The container **must** map a host directory to `/data`. If `/data` is not a volume mount, the app refuses to start — every image pull would otherwise give you an empty database.

### Recommended: Docker Compose in appdata (survives `docker pull`)

```bash
mkdir -p /mnt/user/appdata/morning-news
cd /mnt/user/appdata/morning-news
# Copy docker-compose.unraid.yml and .env here (once; see step 2 above for .env)
docker compose -f docker-compose.unraid.yml up -d
```

Add these to `.env` (in addition to `SESSION_SECRET`, API keys, and bootstrap credentials):

- `DOCKER_IMAGE=youruser/morning-news:latest`
- `HOST_PORT=8084` (or whatever host port you use)
- `APP_DATA_DIR=/mnt/user/appdata/morning-news` (default; same folder is mounted to `/data`)

**Push from your dev machine:**

```bash
npm run unraid:push
```

**Update on the NAS** (pulls the new image, keeps the same `/data` bind mount):

```bash
cd /mnt/user/appdata/morning-news
npm run unraid:pull
# or: docker compose -f docker-compose.unraid.yml pull && docker compose -f docker-compose.unraid.yml up -d
```

### Alternative: Unraid Docker UI

1. Build and push the image (`npm run unraid:push`).
2. Add a container from your Docker Hub repo (see `unraid/morning-news.xml` as a template).
3. **Path mapping (required):** Host `/mnt/user/appdata/morning-news` → Container `/data`
4. Map a host port to container port `8080`.
5. Set environment variables — same names and values as `.env.example` / the tables in [Running your own instance (Docker)](#running-your-own-instance-docker).

When updating via the Unraid UI, use **Apply** on the existing container so the path
mapping is kept. If you delete and recreate the container, re-add the `/data` mapping
before starting it.

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

uvicorn app.main:app --reload --port 8080
# Then open Settings → Connections to add ElevenLabs and an LLM key.
```

`ffmpeg` must be installed locally for audio assembly (`brew install ffmpeg` /
`apt install ffmpeg`).

## Configuration reference

Quick lookup for all environment variables. See [step 2](#2-create-your-env-file) for signup links and setup notes.

| Env var | Required | Where to get it | What it does |
| --- | --- | --- | --- |
| `SESSION_SECRET` | yes | Generate locally | Signs session cookies; encrypts API keys at rest |
| `BOOTSTRAP_USERNAME` | first run | You choose | Creates the initial user when the database is empty |
| `BOOTSTRAP_PASSWORD` | first run | You choose | Password for the initial user |
| `ELEVENLABS_API_KEY` | optional | [ElevenLabs](https://elevenlabs.io/app/settings/api-keys) | Overrides UI — narration (normally set in Connections) |
| `OPENROUTER_API_KEY` | optional | [OpenRouter](https://openrouter.ai/keys) | Overrides UI — script writing via OpenRouter |
| `OPENAI_API_KEY` | optional | [OpenAI](https://platform.openai.com/api-keys) | Overrides UI — script writing via ChatGPT API |
| `ANTHROPIC_API_KEY` | optional | [Anthropic](https://console.anthropic.com/settings/keys) | Overrides UI — script writing via Claude API |
| `LLM_API_KEY` | optional | Your OpenAI-compatible server | Overrides UI — custom endpoint key |
| `LLM_BASE_URL` | optional | e.g. `http://host.docker.internal:11434/v1` | Overrides UI — custom OpenAI-compatible base URL |
| `LLM_PROVIDER` | optional | `openrouter`, `openai`, `anthropic`, or `custom` | Server default when Advanced has no provider selected |
| `ZYTE_API_KEY` | optional | [Zyte](https://www.zyte.com/) | Overrides UI — article extraction fallback |
| `FINNHUB_API_KEY` | optional | [Finnhub](https://finnhub.io/) | Overrides UI — stock watchlist quotes |
| `NEWSDATA_API_KEY` | optional | [NewsData.io](https://newsdata.io/) | Overrides UI — not used yet |
| `BASE_URL` | optional | Your public URL | Canonical HTTPS URL for RSS enclosures behind a reverse proxy |
| `DATA_DIR` | optional | Set in container env | Data root (default `/data` in Docker, `./data` locally) |
| `DOCKER_IMAGE` | Unraid only | Your registry tag | Pre-built image for `docker-compose.unraid.yml` |
| `HOST_PORT` | Unraid only | You choose | Host port mapped to container `8080` |
| `APP_DATA_DIR` | Unraid only | NAS path | Host directory bound to `/data` |

Schedule, location, voice, sources, preferences, and podcast metadata are edited in the web UI and stored in SQLite under `/data`.
