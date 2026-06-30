"""Database models and session management (SQLite via SQLModel)."""

from __future__ import annotations

import secrets
from datetime import datetime
from enum import Enum
from typing import Iterator

from sqlmodel import Field, Session, SQLModel, create_engine, select

from .config import config

engine = create_engine(
    config.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def utcnow() -> datetime:
    return datetime.utcnow()


class MessageStatus(str, Enum):
    pending = "pending"
    resolved = "resolved"


class EpisodeStatus(str, Enum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class HealthCheckCache(SQLModel, table=True):
    """Last successful API-key probe — reused for up to a week if the key is unchanged."""

    check_id: str = Field(primary_key=True)
    status: str
    detail: str = ""
    checked_at: datetime = Field(default_factory=utcnow)
    key_fingerprint: str = ""


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class Settings(SQLModel, table=True):
    """Single-row table (id == 1) holding all user-editable, shared config."""

    id: int | None = Field(default=1, primary_key=True)

    # Schedule
    schedule_hour: int = 7
    schedule_minute: int = 0
    timezone: str = "UTC"

    # Location / weather
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    locality: str = ""
    admin1: str = ""  # state / region for regional news fallbacks
    country: str = ""  # country name for regional news fallbacks
    news_hl: str = "en-US"  # interface language for Google News
    news_gl: str = "US"  # geographic edition
    news_ceid: str = "US:en"  # country:language edition pair
    weather_enabled: bool = True

    # Stocks
    stocks_enabled: bool = False
    stocks_mature_reactions: bool = False

    # Calendar
    calendar_url: str = ""

    # Content shaping
    preferences_text: str = ""  # legacy free-text; superseded by preferred_categories
    preferred_categories: str = ""  # comma-separated category ids
    max_article_length: int = 6000
    target_minutes_min: float = 1.5
    target_minutes_max: float = 3.0

    # TTS
    voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    voice_model: str = "eleven_v3"
    intro_enabled: bool = True
    intro_play_seconds: float = 6.0  # full-volume play time before fade-out begins

    # LLM
    openrouter_model: str = "openai/gpt-4o-mini"

    # Podcast metadata
    podcast_title: str = "Morning News"
    podcast_author: str = "Morning News"
    podcast_description: str = "Your personalized daily news briefing."
    feed_token: str = Field(default_factory=lambda: secrets.token_urlsafe(24))

    updated_at: datetime = Field(default_factory=utcnow)


class Source(SQLModel, table=True):
    """A user-supplied RSS feed URL."""

    id: int | None = Field(default=None, primary_key=True)
    url: str
    name: str = ""
    enabled: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Preference(SQLModel, table=True):
    """An excluded topic chip (e.g. 'war', 'politics')."""

    id: int | None = Field(default=None, primary_key=True)
    topic: str
    created_at: datetime = Field(default_factory=utcnow)


class WatchlistItem(SQLModel, table=True):
    """A stock ticker the household follows in the morning briefing."""

    id: int | None = Field(default=None, primary_key=True)
    symbol: str
    label: str = ""
    enabled: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    """A private, one-time message queued by a user to be read aloud once."""

    id: int | None = Field(default=None, primary_key=True)
    author_user_id: int = Field(index=True, foreign_key="user.id")
    text: str
    status: MessageStatus = Field(default=MessageStatus.pending, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    episode_id: int | None = Field(default=None, foreign_key="episode.id")
    resolved_at: datetime | None = None


class Episode(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    script: str = ""
    audio_path: str | None = None
    duration_seconds: float | None = None
    status: EpisodeStatus = Field(default=EpisodeStatus.pending)
    error: str | None = None
    weather_summary: str = ""
    events_summary: str = ""
    market_summary: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class EpisodeArticle(SQLModel, table=True):
    """A show-notes entry: an article that was used in an episode."""

    id: int | None = Field(default=None, primary_key=True)
    episode_id: int = Field(index=True, foreign_key="episode.id")
    title: str
    publisher: str = ""
    url: str


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_schema()


def _migrate_schema() -> None:
    """Add columns to existing SQLite databases created before schema changes."""

    from sqlalchemy import text

    migrations = (
        "ALTER TABLE settings ADD COLUMN admin1 TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN country TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN intro_play_seconds REAL DEFAULT 6.0",
        "ALTER TABLE settings ADD COLUMN preferred_categories TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN stocks_enabled INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN stocks_mature_reactions INTEGER DEFAULT 0",
        "ALTER TABLE episode ADD COLUMN market_summary TEXT DEFAULT ''",
    )
    with engine.connect() as connection:
        for statement in migrations:
            try:
                connection.execute(text(statement))
                connection.commit()
            except Exception:
                pass


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_settings(session: Session) -> Settings:
    """Return the singleton Settings row, creating it on first access."""

    settings = session.get(Settings, 1)
    if settings is None:
        settings = Settings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings
