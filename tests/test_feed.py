"""Tests for RSS feed generation and show-notes rendering in app/feed.py."""

from __future__ import annotations

import html
from datetime import datetime, timezone

import pytest

from app.db import Episode, EpisodeArticle, EpisodeStatus, ReportedItem, Settings
from app.feed import (
    _episode_subtitle,
    _episode_summary,
    _format_duration,
    _reported_item_html,
    _show_notes_html,
    build_feed,
)


class TestReportedItemHtml:
    def test_renders_link_when_url_present(self):
        item = ReportedItem(item="Project Hail Mary", url="https://goodreads.com/1")
        html_out = _reported_item_html(item)
        assert 'href="https://goodreads.com/1"' in html_out
        assert "Project Hail Mary" in html_out

    def test_renders_plain_text_when_url_empty(self):
        item = ReportedItem(item="Apollo 11", url="")
        assert _reported_item_html(item) == "Apollo 11"

    def test_escapes_html_in_item_text(self):
        item = ReportedItem(item="<script>alert('x')</script>", url="")
        result = _reported_item_html(item)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_escapes_html_in_url(self):
        item = ReportedItem(item="Test", url='https://x.com/"onmouseover="alert(1)')
        result = _reported_item_html(item)
        # The quotes must be escaped so the URL can't break out of the href attribute.
        assert "&quot;" in result
        assert 'href="https://x.com/&quot;' in result


class TestEpisodeSummary:
    def test_includes_description(self):
        episode = Episode(title="T", description="A great episode.")
        summary = _episode_summary(episode, [], [])
        assert "A great episode." in summary

    def test_includes_articles(self):
        episode = Episode(title="T", description="")
        articles = [EpisodeArticle(episode_id=1, title="Story A", url="https://a.com")]
        summary = _episode_summary(episode, articles, [])
        assert "Story A" in summary

    def test_includes_reported_items(self):
        episode = Episode(title="T", description="")
        items = [ReportedItem(item="Book A", url="")]
        summary = _episode_summary(episode, [], items)
        assert "Book A" in summary

    def test_includes_weather_and_market(self):
        episode = Episode(
            title="T", description="", weather_summary="sunny", market_summary="up 2%",
        )
        summary = _episode_summary(episode, [], [])
        assert "sunny" in summary
        assert "up 2%" in summary

    def test_defaults_when_empty(self):
        episode = Episode(title="T", description="")
        assert _episode_summary(episode, [], []) == "Your daily briefing."


class TestEpisodeSubtitle:
    def test_returns_description_when_short(self):
        episode = Episode(title="Title", description="Short desc.")
        assert _episode_subtitle(episode) == "Short desc."

    def test_falls_back_to_title(self):
        episode = Episode(title="Fallback Title", description="")
        assert _episode_subtitle(episode) == "Fallback Title"

    def test_truncates_long_text(self):
        episode = Episode(title="T", description="A" * 300)
        subtitle = _episode_subtitle(episode)
        assert len(subtitle) <= 255
        assert subtitle.endswith("...")


class TestShowNotesHtml:
    def test_renders_description_paragraph(self):
        episode = Episode(title="T", description="A briefing.")
        notes = _show_notes_html(episode, [], [])
        assert "<p>A briefing.</p>" in notes

    def test_renders_article_links(self):
        episode = Episode(title="T", description="")
        articles = [
            EpisodeArticle(episode_id=1, title="Story A", url="https://a.com", publisher="Gazette"),
        ]
        notes = _show_notes_html(episode, articles, [])
        assert 'href="https://a.com"' in notes
        assert "Story A" in notes
        assert "Gazette" in notes

    def test_renders_reported_items_with_links(self):
        episode = Episode(title="T", description="")
        items = [ReportedItem(item="Book A", url="https://goodreads.com/a")]
        notes = _show_notes_html(episode, [], items)
        assert "Mentioned in this episode" in notes
        assert 'href="https://goodreads.com/a"' in notes
        assert "Book A" in notes

    def test_renders_reported_items_without_links(self):
        episode = Episode(title="T", description="")
        items = [ReportedItem(item="Some Topic", url="")]
        notes = _show_notes_html(episode, [], items)
        assert "Some Topic" in notes
        assert "href=" not in notes

    def test_defaults_when_empty(self):
        episode = Episode(title="T", description="")
        notes = _show_notes_html(episode, [], [])
        assert notes == "<p>Your daily briefing.</p>"


class TestFormatDuration:
    def test_formats_seconds_only(self):
        assert _format_duration(45) == "0:45"

    def test_formats_minutes_and_seconds(self):
        assert _format_duration(125) == "2:05"

    def test_formats_hours(self):
        assert _format_duration(3661) == "1:01:01"

    def test_zero(self):
        assert _format_duration(0) == "0:00"


class TestBuildFeed:
    def _settings(self):
        return Settings(
            id=1,
            podcast_title="Test Podcast",
            podcast_author="Test Author",
            podcast_description="A test feed.",
            feed_token="test-token",
        )

    def test_builds_valid_rss_xml(self):
        settings = self._settings()
        episode = Episode(
            id=1,
            title="Episode 1",
            description="First episode.",
            status=EpisodeStatus.ready,
            audio_path="1.mp3",
            duration_seconds=120.0,
            created_at=datetime(2026, 7, 12, 7, 0, 0, tzinfo=timezone.utc),
        )
        episodes = [(episode, [], [], 1024)]

        xml = build_feed(settings, episodes, "https://example.com")
        assert b"<rss" in xml
        assert b"Test Podcast" in xml
        assert b"Episode 1" in xml
        assert b"https://example.com/media/1.mp3" in xml
        assert b"token=" not in xml.replace(b"feed.xml?token=test-token", b"")

    def test_preserves_newest_first_order(self):
        settings = self._settings()
        newest = Episode(
            id=2,
            title="Newest Episode",
            description="",
            status=EpisodeStatus.ready,
            audio_path="2.mp3",
            created_at=datetime(2026, 7, 13, 7, 0, 0, tzinfo=timezone.utc),
        )
        oldest = Episode(
            id=1,
            title="Oldest Episode",
            description="",
            status=EpisodeStatus.ready,
            audio_path="1.mp3",
            created_at=datetime(2026, 7, 12, 7, 0, 0, tzinfo=timezone.utc),
        )
        # Callers pass episodes newest-first; the feed must keep that order.
        xml = build_feed(settings, [(newest, [], [], 1), (oldest, [], [], 1)], "https://example.com")
        assert xml.index(b"Newest Episode") < xml.index(b"Oldest Episode")

    def test_feed_includes_reported_items_in_show_notes(self):
        settings = self._settings()
        episode = Episode(
            id=2,
            title="Book Day",
            description="Book recommendations.",
            status=EpisodeStatus.ready,
            audio_path="2.mp3",
            duration_seconds=90.0,
            created_at=datetime(2026, 7, 12, 7, 0, 0, tzinfo=timezone.utc),
        )
        items = [ReportedItem(item="Dune", url="https://goodreads.com/dune")]
        episodes = [(episode, [], items, 2048)]

        xml = build_feed(settings, episodes, "https://example.com")
        assert b"Dune" in xml
        assert b"goodreads.com/dune" in xml

    def test_feed_includes_article_links_in_show_notes(self):
        settings = self._settings()
        episode = Episode(
            id=3,
            title="News Day",
            description="",
            status=EpisodeStatus.ready,
            audio_path="3.mp3",
            duration_seconds=60.0,
            created_at=datetime(2026, 7, 12, 7, 0, 0, tzinfo=timezone.utc),
        )
        articles = [
            EpisodeArticle(episode_id=3, title="Big Story", url="https://news.example.com/big", publisher="Daily"),
        ]
        episodes = [(episode, articles, [], 512)]

        xml = build_feed(settings, episodes, "https://example.com")
        assert b"Big Story" in xml
        assert b"news.example.com/big" in xml

    def test_empty_episodes_list_produces_valid_feed(self):
        settings = self._settings()
        xml = build_feed(settings, [], "https://example.com")
        assert b"<rss" in xml
        assert b"Test Podcast" in xml
