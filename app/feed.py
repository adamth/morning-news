"""iTunes-compatible podcast RSS generation (feedgen)."""

from __future__ import annotations

import html
from datetime import timezone
from pathlib import Path

from feedgen.feed import FeedGenerator

from .db import Episode, EpisodeArticle, Settings


def _show_notes_html(episode: Episode, articles: list[EpisodeArticle]) -> str:
    parts: list[str] = []
    if episode.description:
        parts.append(f"<p>{html.escape(episode.description)}</p>")
    if episode.weather_summary:
        parts.append(f"<p><strong>Weather:</strong> {html.escape(episode.weather_summary)}</p>")
    if episode.events_summary:
        parts.append(f"<p><strong>Today:</strong> {html.escape(episode.events_summary)}</p>")
    if episode.market_summary:
        parts.append(f"<p><strong>Market:</strong> {html.escape(episode.market_summary)}</p>")
    if articles:
        links = "".join(
            f'<li><a href="{html.escape(article.url)}">{html.escape(article.title)}</a>'
            f"{' — ' + html.escape(article.publisher) if article.publisher else ''}</li>"
            for article in articles
        )
        parts.append(f"<p><strong>In this episode:</strong></p><ul>{links}</ul>")
    return "".join(parts) or "<p>Your daily briefing.</p>"


def build_feed(
    settings: Settings,
    episodes: list[tuple[Episode, list[EpisodeArticle], int]],
    base_url: str,
) -> bytes:
    """Build the podcast RSS XML.

    `episodes` is a list of (episode, show-note articles, audio byte length).
    """

    fg = FeedGenerator()
    fg.load_extension("podcast")

    feed_url = f"{base_url}/feed.xml?token={settings.feed_token}"
    fg.id(feed_url)
    fg.title(settings.podcast_title)
    fg.author({"name": settings.podcast_author})
    fg.link(href=base_url, rel="alternate")
    fg.link(href=feed_url, rel="self")
    fg.language("en")
    fg.description(settings.podcast_description or settings.podcast_title)
    fg.podcast.itunes_author(settings.podcast_author)
    fg.podcast.itunes_summary(settings.podcast_description or settings.podcast_title)
    fg.podcast.itunes_category("News")
    fg.podcast.itunes_explicit("no")

    for episode, articles, byte_length in episodes:
        entry = fg.add_entry()
        media_url = f"{base_url}/media/{episode.id}.mp3?token={settings.feed_token}"
        entry.id(media_url)
        entry.title(episode.title)
        entry.description(_show_notes_html(episode, articles))
        entry.enclosure(media_url, str(byte_length), "audio/mpeg")
        published = episode.created_at.replace(tzinfo=timezone.utc)
        entry.published(published)
        entry.link(href=f"{base_url}/episodes/{episode.id}")
        if episode.duration_seconds:
            entry.podcast.itunes_duration(_format_duration(episode.duration_seconds))

    return fg.rss_str(pretty=True)


def _format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
