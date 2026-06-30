"""Runtime configuration sourced from environment variables.

Secrets (API keys, session secret) live in the environment; everything the user
can change at runtime lives in the database `Settings` row instead.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Load a repo-root `.env` for local dev. Docker / compose inject env directly."""

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env", override=False)


def env_str(name: str) -> str | None:
    """Read a non-empty, trimmed environment variable."""

    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_base_url() -> str | None:
    value = env_str("BASE_URL")
    return value.rstrip("/") if value else None


_load_dotenv()


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "./data")).resolve())

    # External service credentials (optional at boot; features degrade if missing).
    elevenlabs_api_key: str | None = field(default_factory=lambda: env_str("ELEVENLABS_API_KEY"))
    openrouter_api_key: str | None = field(default_factory=lambda: env_str("OPENROUTER_API_KEY"))
    zyte_api_key: str | None = field(default_factory=lambda: env_str("ZYTE_API_KEY"))
    newsdata_api_key: str | None = field(default_factory=lambda: env_str("NEWSDATA_API_KEY"))
    finnhub_api_key: str | None = field(default_factory=lambda: env_str("FINNHUB_API_KEY"))

    # Optional override for RSS enclosure / feed links. When unset, derived per request.
    base_url: str | None = field(default_factory=_env_base_url)

    session_secret: str = field(
        default_factory=lambda: env_str("SESSION_SECRET") or secrets.token_urlsafe(48)
    )

    # First-run bootstrap user.
    bootstrap_username: str | None = field(default_factory=lambda: env_str("BOOTSTRAP_USERNAME"))
    bootstrap_password: str | None = field(default_factory=lambda: env_str("BOOTSTRAP_PASSWORD"))

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'morning_news.db'}"

    @property
    def episodes_dir(self) -> Path:
        return self.data_dir / "episodes"

    @property
    def intro_path(self) -> Path:
        return self.data_dir / "intro.mp3"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_dir.mkdir(parents=True, exist_ok=True)


config = Config()
config.ensure_dirs()
