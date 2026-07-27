"""iTunes-compatible podcast RSS generation (feedgen)."""

from __future__ import annotations

import html
import re
from datetime import timezone

from feedgen.feed import FeedGenerator

from .db import Episode, EpisodeArticle, ReportedItem, Settings

_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(value: str) -> str:
    return html.unescape(_TAG_RE.sub("", value)).strip()


def _episode_summary(
    episode: Episode,
    articles: list[EpisodeArticle],
    reported_items: list[ReportedItem],
) -> str:
    parts: list[str] = []
    if episode.description:
        parts.append(episode.description)
    if episode.weather_summary:
        parts.append(f"Weather: {episode.weather_summary}")
    if episode.events_summary:
        parts.append(f"Today: {episode.events_summary}")
    if episode.market_summary:
        parts.append(f"Market: {episode.market_summary}")
    if articles:
        parts.append("In this episode: " + "; ".join(article.title for article in articles))
    if reported_items:
        parts.append("Mentioned: " + "; ".join(item.item for item in reported_items))
    return " ".join(parts) or "Your daily briefing."


def _episode_subtitle(episode: Episode) -> str:
    text = episode.description or episode.title
    if len(text) <= 255:
        return text
    return text[:252].rstrip() + "..."


def _artwork_url(base_url: str) -> str:
    return f"{base_url}/podcast-artwork.png"


def _show_notes_html(
    episode: Episode,
    articles: list[EpisodeArticle],
    reported_items: list[ReportedItem],
) -> str:
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
    if reported_items:
        items = "".join(
            f"<li>{_reported_item_html(item)}</li>"
            for item in reported_items
        )
        parts.append(f"<p><strong>Mentioned in this episode:</strong></p><ul>{items}</ul>")
    return "".join(parts) or "<p>Your daily briefing.</p>"


def _reported_item_html(item: ReportedItem) -> str:
    title = html.escape(item.item)
    url = (item.url or "").strip()
    if url:
        return f'<a href="{html.escape(url)}">{title}</a>'
    return title


def build_feed(
    settings: Settings,
    episodes: list[tuple[Episode, list[EpisodeArticle], list[ReportedItem], int]],
    base_url: str,
) -> bytes:
    """Build the podcast RSS XML.

    `episodes` is a list of (episode, show-note articles, reported items, audio byte length).
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
    fg.podcast.itunes_category({"cat": "News & Politics"})
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_type("episodic")
    fg.podcast.itunes_image(_artwork_url(base_url))
    if settings.podcast_description:
        subtitle = settings.podcast_description.split(".")[0].strip()
        if subtitle:
            fg.podcast.itunes_subtitle(subtitle[:255])

    for episode, articles, reported_items, byte_length in episodes:
        entry = fg.add_entry(order="append")
        media_url = f"{base_url}/media/{episode.id}.mp3"
        summary = _episode_summary(episode, articles, reported_items)
        show_notes = _show_notes_html(episode, articles, reported_items)
        entry.id(media_url)
        entry.title(episode.title)
        entry.description(show_notes)
        entry.enclosure(media_url, str(byte_length), "audio/mpeg")
        published = episode.created_at.replace(tzinfo=timezone.utc)
        entry.published(published)
        entry.link(href=f"{base_url}/episodes/{episode.id}")
        entry.podcast.itunes_author(settings.podcast_author)
        entry.podcast.itunes_summary(summary)
        entry.podcast.itunes_subtitle(_episode_subtitle(episode))
        entry.podcast.itunes_explicit("no")
        entry.podcast.itunes_episode_type("full")
        if episode.id is not None:
            entry.podcast.itunes_episode(episode.id)
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
