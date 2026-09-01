"""LLM client for summarization and script writing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .credentials import Credentials
from .episode_log import LogTimer, active_log
from .llm_providers import (
    LlmProviderConfig,
    LlmProviderError,
    LlmProviderId,
    resolve_provider_config,
)

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class ArticleInput:
    id: int
    title: str
    publisher: str
    content: str
    source_name: str = ""
    priority: bool = False


@dataclass
class MessageInput:
    id: int
    text: str


@dataclass
class SpecialReport:
    """A weekday-specific report (books, films, true story, …) spliced into the prompt."""

    report_type_id: str
    label: str
    prompt: str
    user_input: str = ""
    covered_items: list[str] = field(default_factory=list)
    variety_axis: str = ""


@dataclass
class ReportedLink:
    """A title/subject covered by a special-report episode and a canonical link for show notes."""

    title: str
    url: str = ""


@dataclass
class EpisodeContent:
    title: str
    description: str
    script: str
    used_article_ids: list[int] = field(default_factory=list)
    used_message_ids: list[int] = field(default_factory=list)
    reported_items: list[str] = field(default_factory=list)
    reported_links: list[ReportedLink] = field(default_factory=list)
    market_comment: str = ""


EPISODE_CONTENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Short episode title",
        },
        "description": {
            "type": "string",
            "description": "One-sentence summary for show notes",
        },
        "script": {
            "type": "string",
            "description": (
                "The full spoken monologue as one continuous block of prose with "
                "correct English punctuation (periods, commas, question marks, "
                "apostrophes), and no line breaks or escape sequences"
            ),
        },
        "used_article_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Article ids from the candidate list that were included in the episode",
        },
        "used_message_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Personal message ids that were read aloud in the episode",
        },
        "reported_items": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Only when this is a special-report episode (books, films, true "
                "story, etc.): the titles or subjects you actually covered, one "
                "entry per item. Empty array for a regular news episode."
            ),
        },
        "market_comment": {
            "type": "string",
            "description": (
                "The one wry aside about the stock market exactly as it appears in "
                "the script, verbatim. Empty string when the episode has no market "
                "segment. This is how the show remembers not to repeat a joke."
            ),
        },
        "reported_links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The title or subject of the item, as you said it on air",
                    },
                    "url": {
                        "type": "string",
                        "description": (
                            "A canonical, stable link the listener can open to learn "
                            "more or find the item. Use Goodreads book pages for "
                            "books, IMDb titles for films/TV, Wikipedia or another "
                            "reputable source for true stories, and the source "
                            "article URL for a news deep dive. Omit the entry if no "
                            "suitable public link exists."
                        ),
                    },
                },
                "required": ["title", "url"],
                "additionalProperties": False,
            },
            "description": (
                "Only when this is a special-report episode: one {title, url} "
                "entry per item you covered, so show notes can link to it. Empty "
                "array for a regular news episode or when no link applies."
            ),
        },
    },
    "required": ["title", "description", "script", "used_article_ids", "used_message_ids", "reported_items", "reported_links", "market_comment"],
    "additionalProperties": False,
}


def _provider_config(
    *,
    credentials: Credentials,
    llm_provider: str = "",
    llm_model: str = "",
) -> LlmProviderConfig:
    try:
        return resolve_provider_config(
            credentials=credentials,
            settings_provider=llm_provider,
            settings_model=llm_model,
        )
    except LlmProviderError as error:
        raise LLMError(str(error)) from error


def _chat_completion(**kwargs: object) -> str:
    from .llm_providers import chat_completion

    try:
        return chat_completion(**kwargs)
    except LlmProviderError as error:
        raise LLMError(str(error)) from error


def summarize_article(
    text: str,
    target_chars: int,
    *,
    credentials: Credentials,
    llm_provider: str = "",
    llm_model: str = "",
) -> str:
    """Condense a long article to roughly `target_chars` characters."""

    target_words = max(60, target_chars // 6)
    provider_config = _provider_config(
        credentials=credentials,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    return _chat_completion(
        provider_config=provider_config,
        system=(
            "You compress news articles into tight, factual summaries that "
            "preserve the who/what/where/when. No preamble, no opinion."
        ),
        user=f"Summarize the following article in about {target_words} words.\n\n{text}",
        temperature=0.2,
    )


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
    special_report: SpecialReport | None = None,
    past_market_comments: list[str] | None = None,
) -> str:
    midpoint_words = int(((target_min + target_max) / 2) * 150)

    def _feed_tag(item: ArticleInput) -> str:
        if item.priority:
            return f" (priority feed: {item.source_name or item.publisher})"
        if item.source_name:
            return f" (feed: {item.source_name})"
        return ""

    article_block = "\n\n".join(
        f"[article {item.id}]{_feed_tag(item)} "
        f"{item.title} ({item.publisher})\n{item.content[:4000]}"
        for item in articles
    ) or "(no articles available)"

    message_block = "\n".join(f"[message {item.id}] {item.text}" for item in messages) or "(none)"
    events_block = "\n".join(f"- {event}" for event in events) or "(none today)"
    excluded_block = ", ".join(excluded_topics) if excluded_topics else "(none)"
    market_block = market_text or "(not included today)"
    reaction_block = market_reaction or "(none)"
    past_comments_block = (
        "\n".join(f"- {comment}" for comment in (past_market_comments or []))
        or "(none yet)"
    )

    if special_report is not None:
        user_input_block = special_report.user_input.strip() or "(none provided)"
        if special_report.covered_items:
            covered_block = "\n".join(f"- {item}" for item in special_report.covered_items)
            covered_clause = (
                "\n\nALREADY COVERED — the complete list of everything this show has used on an "
                f"episode of \"{special_report.label}\". This is a hard exclusion: do not repeat any of "
                "them, and do not pick a near-variant of one (the same event told from another "
                "angle, a sequel, or another work by the same author or director counts as a "
                "repeat). Check your choice against this list before you write, and if the first "
                "idea that comes to mind is on it, discard that idea and find another:\n"
                f"{covered_block}"
            )
        else:
            covered_clause = ""
        if special_report.variety_axis:
            variety_clause = (
                "\n\nTODAY'S ANGLE (rotates every episode so the show doesn't circle the same "
                f"few subjects): {special_report.variety_axis}. Follow it unless the listener's "
                "guidance above points elsewhere, in which case the listener wins."
            )
        else:
            variety_clause = ""
        special_section = f"""SPECIAL REPORT — {special_report.label.upper()}:
{special_report.prompt}

LISTENER'S TASTE / GUIDANCE FOR THIS REPORT:
{user_input_block}{covered_clause}{variety_clause}

TODAY IS A SPECIAL-REPORT DAY. Lead with the greeting, weather, and (if any) calendar events,
then deliver the special report as the body of the episode. Treat today's candidate news articles
as background only — use them only if the report above asks for news (e.g. the "deep dive" report).
Skip the regular news roundup unless the report's instructions explicitly call for it.

When you finish, list every title or subject you actually covered in the `reported_items` array
of your JSON output (one entry per item), named specifically enough to identify it on its own —
"The 1904 Kiruna avalanche", not "an avalanche". This array is the only record the show keeps,
so an item you leave out will come back around and be repeated.

Also fill the `reported_links` array with one {{title, url}} entry per item you covered, so show
notes can link listeners to each one. Use a canonical, stable public URL: Goodreads book pages
for books, IMDb titles for films and TV shows, Wikipedia or another reputable source for true
stories, and the source article URL for a news deep dive. If no public link truly fits an item,
omit that entry from `reported_links` (but still list the item in `reported_items`)."""
    else:
        special_section = ""

    return f"""You are the writer and host of a personal daily audio news briefing called "{podcast_title}".
Today is {date_text}. The listener's local area is {locality or "unspecified"}.

Write a natural, concise spoken monologue of about {midpoint_words} words \
(target {target_min}-{target_max} minutes at ~150 words/minute). Sound like a calm, \
competent local newsreader — friendly but efficient. Do NOT include stage directions, \
headers, markdown, line breaks, or escape sequences (no \\n, \\t, etc.). The script must \
be one continuous block of prose with correct English punctuation — output only what \
should be spoken aloud.

PUNCTUATION (required — TTS uses it for pacing and intonation):
- End every sentence with a period, question mark, or exclamation mark.
- Use commas for natural pauses: between clauses, in lists, and after brief transitions.
- Use apostrophes in contractions (it's, here's, we're).
- Dates use a comma before the year (July 2, 2026), matching the date given above.
- Do not omit punctuation or run sentences together without commas or periods.

STYLE:
- Use short transitions so the listener always knows where they are: e.g. "For today's weather…", \
"Turning to the news…", "In local news…", "Also today…", "Next…". One brief phrase between \
sections or stories is fine — it helps pacing.
- Keep transitions SHORT (under ~8 words). Never pad with reflective or motivational commentary.
- Do NOT use lofty meta-commentary about the show or how the listener should feel. Avoid: \
"stories that caught my eye", "I hope you feel connected", "I hope you're cozy", \
"encouraging local stories", "leaves you feeling", "a quiet one", "catch up on things", \
"a little downtime", or long previews of what you're about to cover.
- Do not introduce yourself by name — the audio opens with a separate line naming the narrator.
- Greeting: one or two short sentences (day/date, maybe a quick "here's your briefing"). \
When stating the date, use the exact format given above (e.g. July 2, 2026) — always include \
a comma before the year.
- Sign-off: one or two short sentences. Warm is fine; a paragraph of reflection is not.
- Weather and events: state the facts, then a clear handoff to the next section.
- Market watch: one or two sentences on the aggregate numbers only. Then ONE brief wry reaction \
— kitchen-table humor, never investment advice. Do not name tickers. The reaction hint below sets \
the tone, not the words: write a fresh line rather than paraphrasing it, and never reuse a joke, \
image, or turn of phrase from the past asides listed below.
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

MARKET REACTION HINT (tone calibration only — how wry to be, not what to say):
{reaction_block}

MARKET ASIDES ALREADY USED ON PAST EPISODES (do not repeat or rework any of these — the listener
hears one of these every day, so today's must be a new observation, not a rephrasing):
{past_comments_block}

After writing, copy today's market aside verbatim into the `market_comment` field of your JSON
output, or leave it an empty string if the episode has no market segment.

CALENDAR EVENTS TODAY (an event prefixed with a name, like "Work:", says which calendar \
it came from — say whose day it belongs to rather than reading the prefix as part of the title):
{events_block}

PERSONAL MESSAGES TO INCLUDE (read each one that you use, then list its id in used_message_ids):
{message_block}

CANDIDATE NEWS ARTICLES (pick the strongest stories; use priorities above as a tie-breaker):
- Articles marked with "feed:" come from RSS feeds the listener added — include at least one when relevant.
- Articles marked with "priority feed:" are must-include: cover EVERY one of them, at least briefly. \
They come from rarely-updated feeds the listener never wants to miss.
{article_block}

{special_section}"""


def generate_episode(
    *,
    credentials: Credentials,
    llm_provider: str = "",
    llm_model: str = "",
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
    special_report: SpecialReport | None = None,
    past_market_comments: list[str] | None = None,
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
        special_report=special_report,
        past_market_comments=past_market_comments,
    )

    provider_config = _provider_config(
        credentials=credentials,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    timer = LogTimer.start()
    system = (
        "You write clear, natural spoken news scripts with correct English punctuation — "
        "factual but easy to follow, with brief transitions between sections."
    )
    raw = _chat_completion(
        provider_config=provider_config,
        system=system,
        user=prompt,
        temperature=0.5,
        response_schema=EPISODE_CONTENT_JSON_SCHEMA,
        response_schema_name="episode_content",
    )
    audit = active_log()
    if audit is not None:
        audit.record(
            "llm",
            "Chat completion (write script)",
            summary=f"{len(raw)} chars returned",
            request={
                "provider": provider_config.provider.value,
                "model": provider_config.model,
                "temperature": 0.5,
                "response_schema": "episode_content",
                "article_count": len(articles),
                "message_count": len(messages),
                "prompt_chars": len(prompt),
                "system": system,
                "prompt": prompt,
            },
            response={"raw_chars": len(raw), "raw": raw},
            duration_ms=timer.elapsed_ms(),
        )
    return _parse_episode_content(raw)


def prepare_spoken_text(text: str) -> str:
    """Normalize script text for TTS — no line breaks or literal escape sequences."""

    cleaned = text.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    cleaned = re.sub(r"[\r\n\t\f\v]+", " ", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def _parse_episode_content(raw: str) -> EpisodeContent:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Some models wrap JSON in prose or fences; salvage the outermost object.
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise LLMError("LLM did not return JSON")
        data = json.loads(raw[start : end + 1])

    script = prepare_spoken_text(data.get("script") or "")
    if not script:
        raise LLMError("LLM returned an empty script")

    return EpisodeContent(
        title=(data.get("title") or "Daily Briefing").strip(),
        description=(data.get("description") or "").strip(),
        script=script,
        used_article_ids=[int(value) for value in data.get("used_article_ids", []) if _is_int(value)],
        used_message_ids=[int(value) for value in data.get("used_message_ids", []) if _is_int(value)],
        reported_items=[
            str(value).strip()
            for value in data.get("reported_items", [])
            if str(value).strip()
        ],
        reported_links=_parse_reported_links(data.get("reported_links")),
        market_comment=prepare_spoken_text(str(data.get("market_comment") or "")),
    )


def _is_int(value) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _parse_reported_links(raw: object) -> list[ReportedLink]:
    """Extract {title, url} entries from the LLM's reported_links output."""

    if not isinstance(raw, list):
        return []
    links: list[ReportedLink] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not title:
            continue
        links.append(ReportedLink(title=title, url=url))
    return links
