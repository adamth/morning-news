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
    weather_provider: str = "open_meteo"  # weatherapi | open_meteo

    # Stocks
    stocks_enabled: bool = False
    stocks_mature_reactions: bool = False

    # Content shaping
    preferences_text: str = ""  # legacy free-text; superseded by preferred_categories
    preferred_categories: str = ""  # comma-separated category ids
    max_article_length: int = 6000
    target_minutes_min: float = 1.5
    target_minutes_max: float = 3.0

    # TTS
    tts_provider: str = ""  # elevenlabs | speechify; empty = auto-detect from saved keys
    voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    voice_model: str = "eleven_v3"
    voice_language: str = ""  # empty = derive from news_hl
    voice_accent: str = ""  # empty = any accent
    voice_randomize: bool = False
    speechify_emotion: str = ""  # Speechify SSML emotion; empty = natural delivery
    intro_enabled: bool = True
    intro_play_seconds: float = 6.0  # full-volume play time before fade-out begins
    outro_enabled: bool = True
    outro_play_seconds: float = 2.0  # seconds of outro mixed with the end of narration

    # LLM
    llm_provider: str = ""  # openrouter | openai | anthropic | custom; empty = auto-detect
    llm_model: str = "openai/gpt-4o-mini"
    llm_base_url: str = ""  # custom OpenAI-compatible endpoint

    # API credentials (Fernet-encrypted; enter via Settings → Connections)
    elevenlabs_api_key_enc: str = ""
    speechify_api_key_enc: str = ""
    openrouter_api_key_enc: str = ""
    openai_api_key_enc: str = ""
    anthropic_api_key_enc: str = ""
    llm_api_key_enc: str = ""
    zyte_api_key_enc: str = ""
    finnhub_api_key_enc: str = ""
    newsdata_api_key_enc: str = ""
    weatherapi_api_key_enc: str = ""

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
    # Low-volume feeds (a few stories a week) whose new articles must always
    # make the episode instead of competing with the daily headline firehose.
    priority: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class CalendarFeed(SQLModel, table=True):
    """A calendar the household subscribes to — a public .ics link or a CalDAV URL.

    `label` names the calendar out loud ("Work", "Sophie's school"), so events from
    several calendars stay distinguishable in the spoken episode.
    """

    id: int | None = Field(default=None, primary_key=True)
    url: str
    label: str = ""
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


class WeeklyReport(SQLModel, table=True):
    """Per-weekday special report configuration.

    One row per day_of_week (0=Monday … 6=Sunday). `report_type` empty means
    "regular daily news"; otherwise it's a key from `app.report_types.REPORT_TYPES`.
    `user_input` carries free-text hints (e.g. books the household enjoys) that
    the report type uses to tailor the episode.
    """

    id: int | None = Field(default=None, primary_key=True)
    day_of_week: int = Field(index=True, unique=True)
    report_type: str = ""
    user_input: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class ReportedItem(SQLModel, table=True):
    """A title or subject covered by a past special-report episode.

    Used to keep the next episode of the same type from repeating itself:
    the pipeline loads the most recent items for a given report type and feeds
    them back into the LLM prompt as "do not repeat these".
    """

    id: int | None = Field(default=None, primary_key=True)
    report_type: str = Field(index=True)
    item: str
    url: str = ""
    episode_id: int | None = Field(default=None, foreign_key="episode.id")
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


class EpisodeLogEntry(SQLModel, table=True):
    """One auditable step during episode generation (API call, AI prompt, etc.)."""

    id: int | None = Field(default=None, primary_key=True)
    episode_id: int = Field(index=True, foreign_key="episode.id")
    category: str = Field(index=True)
    operation: str
    status: str = "success"
    summary: str = ""
    request_data: str = ""
    response_data: str = ""
    duration_ms: float | None = None
    sequence: int = 0
    created_at: datetime = Field(default_factory=utcnow)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_schema()
    _import_env_secrets()


def _import_env_secrets() -> None:
    from .credentials import import_env_secrets_if_empty

    with Session(engine) as session:
        settings = get_settings(session)
        if import_env_secrets_if_empty(settings):
            settings.updated_at = utcnow()
            session.add(settings)
            session.commit()


def _migrate_schema() -> None:
    """Add columns to existing SQLite databases created before schema changes."""

    from sqlalchemy import text

    migrations = (
        "ALTER TABLE settings ADD COLUMN admin1 TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN country TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN intro_play_seconds REAL DEFAULT 6.0",
        "ALTER TABLE settings ADD COLUMN outro_enabled INTEGER DEFAULT 1",
        "ALTER TABLE settings ADD COLUMN outro_play_seconds REAL DEFAULT 6.0",
        "ALTER TABLE settings ADD COLUMN preferred_categories TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN stocks_enabled INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN stocks_mature_reactions INTEGER DEFAULT 0",
        "ALTER TABLE episode ADD COLUMN market_summary TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN voice_language TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN voice_accent TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN voice_randomize INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN llm_provider TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN llm_model TEXT DEFAULT ''",
        "UPDATE settings SET llm_model = openrouter_model WHERE (llm_model IS NULL OR llm_model = '') AND openrouter_model IS NOT NULL AND openrouter_model != ''",
        "ALTER TABLE settings ADD COLUMN llm_base_url TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN elevenlabs_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN speechify_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN tts_provider TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN openrouter_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN openai_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN anthropic_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN llm_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN zyte_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN finnhub_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN newsdata_api_key_enc TEXT DEFAULT ''",
        "ALTER TABLE source ADD COLUMN priority INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN speechify_emotion TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN weather_provider TEXT DEFAULT 'metno'",
        "ALTER TABLE settings ADD COLUMN accuweather_api_key_enc TEXT DEFAULT ''",
        "UPDATE settings SET weather_provider = 'metno' WHERE weather_provider IS NULL OR weather_provider = '' OR weather_provider = 'accuweather'",
        "ALTER TABLE settings ADD COLUMN weatherapi_api_key_enc TEXT DEFAULT ''",
        "UPDATE settings SET weather_provider = 'open_meteo' WHERE weather_provider = 'metno'",
        "ALTER TABLE reporteditem ADD COLUMN url TEXT DEFAULT ''",
        "INSERT INTO calendarfeed (url, label, enabled, created_at) "
        "SELECT calendar_url, 'Family', 1, CURRENT_TIMESTAMP FROM settings "
        "WHERE calendar_url IS NOT NULL AND calendar_url != ''",
        "UPDATE settings SET calendar_url = ''",
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
