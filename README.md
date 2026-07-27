# Morning News

Your household's own daily news podcast. Every morning, Morning News gathers your local
news, weather, calendar, and any notes you've queued for each other, has an LLM write a
short (1.5–3 minute) spoken script, narrates it with a lifelike voice, and publishes it
to a private RSS feed you can subscribe to in any podcast app.

It's self-hosted, multi-user, and runs in a single Docker container — designed for a home
server or NAS.

**How an episode is made:**

1. **Gather** — local news (an auto-generated Google News feed for your area, plus any RSS
  feeds you add), today's weather (WeatherAPI.com or Open-Meteo), calendar events (CalDAV or a public
   `.ics` URL), and private messages queued by household members.
2. **Write** — an LLM filters stories against your preferences ("no war or politics"),
  then writes a natural-sounding script.
3. **Speak** — ElevenLabs or Speechify synthesizes the narration; ffmpeg adds your
  intro/outro music and normalizes loudness.
4. **Publish** — the episode lands in an RSS feed with show notes linking each source.

Other things it does: per-person logins with one shared daily episode, private one-time
messages ("happy anniversary!" read aloud once, invisible to the other person until it
airs), topic exclusions, a stock watchlist, and tiered article extraction that falls back
to the Zyte API for paywalled or JavaScript-heavy pages.

## API keys you'll need

You add API keys **in the web UI** (Settings → Connections) after your first login — not
in config files. They're encrypted and stored in the app's database.

**Required — the podcast can't be made without these two:**


| Service                                                                                                                                                                                                                | Sign up                                          | Used for        |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | --------------- |
| One TTS provider — [ElevenLabs](https://elevenlabs.io/app/settings/api-keys) or [Speechify](https://platform.speechify.ai)                                                                                             | Both have free tiers                             | Voice narration |
| One LLM provider — [OpenRouter](https://openrouter.ai/keys), [OpenAI](https://platform.openai.com/api-keys), [Anthropic](https://console.anthropic.com/settings/keys), or any OpenAI-compatible endpoint (e.g. Ollama) | OpenRouter is the easiest way to try many models | Script writing  |


**Optional — add later if you want the feature:**


| Service                        | Sign up             | Used for                                                |
| ------------------------------ | ------------------- | ------------------------------------------------------- |
| [WeatherAPI.com](https://www.weatherapi.com/signup.aspx) | Free tier (1M calls/month) | More accurate daily forecasts |
| [Finnhub](https://finnhub.io/) | Free tier available | Stock watchlist quotes                                  |
| [Zyte](https://www.zyte.com/)  | Paid                | Extracting article text from paywalled / JS-heavy pages |


Open-Meteo and Google News need no keys or accounts.

## Quick start (Docker)

Prerequisites: [Docker](https://docs.docker.com/get-docker/) with Compose v2.

**1. Get the code**

```bash
git clone https://github.com/adamth/morning-news.git
cd morning-news
```

**2. Create your `.env`**

```bash
cp .env.example .env
```

Only three values are needed to start:


| Variable             | What it is                                                                                                                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SESSION_SECRET`     | Random secret that signs login cookies and encrypts stored API keys. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it logs everyone out and invalidates saved keys. |
| `BOOTSTRAP_USERNAME` | Username for the first admin account (used only when the database is empty).                                                                                                                                 |
| `BOOTSTRAP_PASSWORD` | Password for that account. Change it after logging in.                                                                                                                                                       |


**3. Start the container**

```bash
docker compose up -d --build
```

Data (database, episodes, uploaded media) lives in the named volume
`morning-news-data`. To use a host directory instead (common on a NAS), copy
`docker-compose.override.example.yml` to `docker-compose.override.yml` and edit the path
— Compose merges it automatically. The app refuses to start if `/data` isn't a persistent
volume, so you can't accidentally run with ephemeral storage.

**4. Log in and set up**

1. Open `http://localhost:8080` (or `http://<your-host>:8080`).
2. Log in with your bootstrap credentials.
3. **Settings → Connections** — add a narration key (ElevenLabs or Speechify) and one LLM provider key (see
  [API keys](#api-keys-youll-need) above).
4. **Settings → Advanced** — pick the LLM provider and model for script writing.
5. **Settings → Basic** — location, schedule, RSS sources, voice, topic exclusions.
6. **System status** — confirm everything connects.
7. Copy the **RSS feed URL** from the dashboard into your podcast app. The URL contains
  an unguessable token so podcast apps can subscribe without logging in - treat
   it like a password. Episode audio itself is served without a token, and the newest
   episode is always available at `/media/latest.mp3`.

**Updating:** `git pull && docker compose up -d --build`

**Backing up:** copy the `morning-news-data` volume (or your bind-mounted directory). It
holds the database, episodes, and uploaded media.

## Local development

```bash
npm run dev
# Then open Settings → Connections to add a narration key (ElevenLabs or Speechify) and an LLM key.
```

If the [Infisical CLI](https://infisical.com/docs/cli/overview) is installed, the dev
script injects secrets with `infisical run` (project config in `.infisical.json`, run
`infisical login` once). Without the CLI it falls back to sourcing `.env`. Docker
deploys are unaffected and keep using `.env`.

`ffmpeg` must be installed locally for audio assembly (`brew install ffmpeg` /
`apt install ffmpeg`).

## Environment variable reference

Everything except the first three is optional. API keys set as environment variables
override keys saved in the web UI (useful for Docker automation).


| Env var              | Required  | What it does                                                                                              |
| -------------------- | --------- | --------------------------------------------------------------------------------------------------------- |
| `SESSION_SECRET`     | yes       | Signs session cookies; encrypts API keys at rest                                                          |
| `BOOTSTRAP_USERNAME` | first run | Creates the initial user when the database is empty                                                       |
| `BOOTSTRAP_PASSWORD` | first run | Password for the initial user                                                                             |
| `ELEVENLABS_API_KEY` | —         | Overrides the key saved in Connections                                                                    |
| `SPEECHIFY_API_KEY`  | —         | Overrides the key saved in Connections                                                                    |
| `OPENROUTER_API_KEY` | —         | Overrides the key saved in Connections                                                                    |
| `OPENAI_API_KEY`     | —         | Overrides the key saved in Connections                                                                    |
| `ANTHROPIC_API_KEY`  | —         | Overrides the key saved in Connections                                                                    |
| `LLM_API_KEY`        | —         | Key for a custom OpenAI-compatible endpoint                                                               |
| `LLM_BASE_URL`       | —         | Custom endpoint URL, e.g. `http://host.docker.internal:11434/v1` for Ollama                               |
| `LLM_PROVIDER`       | —         | Server default provider (`openrouter`, `openai`, `anthropic`, `custom`) when none is selected in Advanced |
| `ZYTE_API_KEY`       | —         | Overrides the key saved in Connections                                                                    |
| `FINNHUB_API_KEY`    | —         | Overrides the key saved in Connections                                                                    |
| `NEWSDATA_API_KEY`   | —         | Reserved; not used yet                                                                                    |
| `BASE_URL`           | —         | Force a canonical public URL for RSS/episode links (otherwise derived from each request)                  |
| `DATA_DIR`           | —         | Data root (default `/data` in Docker, `./data` locally)                                                   |


Everything else — schedule, location, voice, sources, topic exclusions, calendar URL,
podcast title — is configured in the web UI and stored in SQLite under `/data`.