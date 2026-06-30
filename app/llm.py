"""OpenRouter (OpenAI-compatible) client for summarization and script writing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI

from .config import config

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _client() -> OpenAI:
    if not config.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not configured")
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.openrouter_api_key,
        default_headers={
            "HTTP-Referer": config.base_url or "http://localhost",
            "X-Title": "Morning News Podcast Generator",
        },
    )


@dataclass
class ArticleInput:
    id: int
    title: str
    publisher: str
    content: str
    source_name: str = ""


@dataclass
class MessageInput:
    id: int
    text: str


@dataclass
class EpisodeContent:
    title: str
    description: str
    script: str
    used_article_ids: list[int] = field(default_factory=list)
    used_message_ids: list[int] = field(default_factory=list)


def summarize_article(text: str, target_chars: int, model: str) -> str:
    """Condense a long article to roughly `target_chars` characters."""

    target_words = max(60, target_chars // 6)
    client = _client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You compress news articles into tight, factual summaries that "
                    "preserve the who/what/where/when. No preamble, no opinion."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Summarize the following article in about {target_words} words.\n\n{text}"
                ),
            },
        ],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def _build_generation_prompt(
    *,
    podcast_title: str,
    date_text: str,
    locality: str,
    target_min: float,
    target_max: float,
    priorities_text: str,
    excluded_topics: list[str],
    weather_text: str,
    market_text: str,
    market_reaction: str,
    events: list[str],
    messages: list[MessageInput],
    articles: list[ArticleInput],
) -> str:
    midpoint_words = int(((target_min + target_max) / 2) * 150)

    article_block = "\n\n".join(
        f"[article {item.id}]"
        f"{f' (feed: {item.source_name})' if item.source_name else ''} "
        f"{item.title} ({item.publisher})\n{item.content[:4000]}"
        for item in articles
    ) or "(no articles available)"

    message_block = "\n".join(f"[message {item.id}] {item.text}" for item in messages) or "(none)"
    events_block = "\n".join(f"- {event}" for event in events) or "(none today)"
    excluded_block = ", ".join(excluded_topics) if excluded_topics else "(none)"
    market_block = market_text or "(not included today)"
    reaction_block = market_reaction or "(none)"

    return f"""You are the writer and host of a personal daily audio news briefing called "{podcast_title}".
Today is {date_text}. The listener's local area is {locality or "unspecified"}.

Write a natural, concise spoken monologue of about {midpoint_words} words \
(target {target_min}-{target_max} minutes at ~150 words/minute). Sound like a calm, \
competent local newsreader — friendly but efficient. Do NOT include stage directions, \
headers, or markdown. Output only what should be spoken.

STYLE:
- Use short transitions so the listener always knows where they are: e.g. "For today's weather…", \
"Turning to the news…", "In local news…", "Also today…", "Next…". One brief phrase between \
sections or stories is fine — it helps pacing.
- Keep transitions SHORT (under ~8 words). Never pad with reflective or motivational commentary.
- Do NOT use lofty meta-commentary about the show or how the listener should feel. Avoid: \
"stories that caught my eye", "I hope you feel connected", "I hope you're cozy", \
"encouraging local stories", "leaves you feeling", "a quiet one", "catch up on things", \
"a little downtime", or long previews of what you're about to cover.
- Greeting: one or two short sentences (day/date, maybe a quick "here's your briefing").
- Sign-off: one or two short sentences. Warm is fine; a paragraph of reflection is not.
- Weather and events: state the facts, then a clear handoff to the next section.
- Market watch: one or two sentences on the aggregate numbers only. Then ONE brief wry reaction \
inspired by the reaction hint — kitchen-table humor, never investment advice. Do not name tickers.
- News: open each story with the headline fact; use a brief transition between stories so \
one doesn't blur into the next. Prefer 3–5 strong stories over many thin ones.
- Personal messages: introduce briefly ("A quick message from…"), read plainly, move on.

STRUCTURE (adapt naturally, omit empty sections):
1. Brief greeting with day/date.
2. Today's weather, if provided.
3. Stock watchlist summary, if provided — OVERALL performance only; never list individual tickers or per-stock percentages.
4. Calendar events for today, if any.
5. The most relevant local/regional news stories.
6. Any personal messages, if any.
7. One-line sign-off.

STORY PRIORITIES (soft guidance — prefer these when picking articles, but they are NOT \
hard rules; a strong story outside these categories is still worth including):
{priorities_text}

EXCLUDED TOPICS (never include stories primarily about these): {excluded_block}

WEATHER: {weather_text or "(unavailable)"}

STOCK WATCHLIST (aggregate 24-hour performance — do NOT read individual stocks):
{market_block}

MARKET REACTION HINT (paraphrase into one short spoken aside; do not read verbatim if stiff):
{reaction_block}

CALENDAR EVENTS TODAY:
{events_block}

PERSONAL MESSAGES TO INCLUDE (read each one that you use, then list its id in used_message_ids):
{message_block}

CANDIDATE NEWS ARTICLES (pick the strongest stories; use priorities above as a tie-breaker):
- Articles marked with "feed:" come from RSS feeds the listener added — include at least one when relevant.
{article_block}

Respond ONLY with a JSON object of this exact shape:
{{
  "title": "short episode title",
  "description": "one-sentence summary for show notes",
  "script": "the full spoken monologue",
  "used_article_ids": [list of integer article ids you actually used],
  "used_message_ids": [list of integer message ids you actually read]
}}"""


def generate_episode(
    *,
    model: str,
    podcast_title: str,
    date_text: str,
    locality: str,
    target_min: float,
    target_max: float,
    priorities_text: str,
    excluded_topics: list[str],
    weather_text: str,
    market_text: str = "",
    market_reaction: str = "",
    events: list[str],
    messages: list[MessageInput],
    articles: list[ArticleInput],
) -> EpisodeContent:
    prompt = _build_generation_prompt(
        podcast_title=podcast_title,
        date_text=date_text,
        locality=locality,
        target_min=target_min,
        target_max=target_max,
        priorities_text=priorities_text,
        excluded_topics=excluded_topics,
        weather_text=weather_text,
        market_text=market_text,
        market_reaction=market_reaction,
        events=events,
        messages=messages,
        articles=articles,
    )

    client = _client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write clear, natural spoken news scripts — factual but easy to follow, "
                    "with brief transitions between sections. You always return valid JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    return _parse_episode_content(raw)


def _parse_episode_content(raw: str) -> EpisodeContent:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Some models wrap JSON in prose or fences; salvage the outermost object.
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise LLMError("LLM did not return JSON")
        data = json.loads(raw[start : end + 1])

    script = (data.get("script") or "").strip()
    if not script:
        raise LLMError("LLM returned an empty script")

    return EpisodeContent(
        title=(data.get("title") or "Daily Briefing").strip(),
        description=(data.get("description") or "").strip(),
        script=script,
        used_article_ids=[int(value) for value in data.get("used_article_ids", []) if _is_int(value)],
        used_message_ids=[int(value) for value in data.get("used_message_ids", []) if _is_int(value)],
    )


def _is_int(value) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False
