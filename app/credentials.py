"""Load and store API credentials — encrypted in the database, env vars as override."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

from .config import config, env_str

if TYPE_CHECKING:
    from .db import Settings

logger = logging.getLogger(__name__)

_SECRET_FIELDS: tuple[tuple[str, str], ...] = (
    ("elevenlabs_api_key_enc", "ELEVENLABS_API_KEY"),
    ("speechify_api_key_enc", "SPEECHIFY_API_KEY"),
    ("openrouter_api_key_enc", "OPENROUTER_API_KEY"),
    ("openai_api_key_enc", "OPENAI_API_KEY"),
    ("anthropic_api_key_enc", "ANTHROPIC_API_KEY"),
    ("llm_api_key_enc", "LLM_API_KEY"),
    ("zyte_api_key_enc", "ZYTE_API_KEY"),
    ("finnhub_api_key_enc", "FINNHUB_API_KEY"),
    ("newsdata_api_key_enc", "NEWSDATA_API_KEY"),
    ("weatherapi_api_key_enc", "WEATHERAPI_API_KEY"),
)


def _fernet() -> Fernet:
    digest = hashlib.sha256(config.session_secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    value = plaintext.strip()
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    if not ciphertext or not ciphertext.strip():
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning("Could not decrypt a stored API key — re-enter it in Settings → Connections")
        return None


def secret_is_stored(encrypted: str | None) -> bool:
    return bool(encrypted and encrypted.strip())


def resolve_secret(*, env_value: str | None, encrypted: str | None) -> str | None:
    """Environment value wins when set; otherwise use the encrypted database value."""

    if env_value:
        return env_value
    return decrypt_secret(encrypted)


def fingerprint_secret(value: str | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Credentials:
    elevenlabs_api_key: str | None = None
    speechify_api_key: str | None = None
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    zyte_api_key: str | None = None
    finnhub_api_key: str | None = None
    newsdata_api_key: str | None = None
    weatherapi_api_key: str | None = None

    elevenlabs_from_env: bool = False
    speechify_from_env: bool = False
    openrouter_from_env: bool = False
    openai_from_env: bool = False
    anthropic_from_env: bool = False
    llm_from_env: bool = False
    zyte_from_env: bool = False
    finnhub_from_env: bool = False
    newsdata_from_env: bool = False
    weatherapi_from_env: bool = False

    elevenlabs_stored: bool = False
    speechify_stored: bool = False
    openrouter_stored: bool = False
    openai_stored: bool = False
    anthropic_stored: bool = False
    llm_stored: bool = False
    zyte_stored: bool = False
    finnhub_stored: bool = False
    newsdata_stored: bool = False
    weatherapi_stored: bool = False


def load_credentials(settings: Settings) -> Credentials:
    def pick(
        env_name: str,
        encrypted: str | None,
    ) -> tuple[str | None, bool, bool]:
        env_value = env_str(env_name)
        stored = secret_is_stored(encrypted)
        return resolve_secret(env_value=env_value, encrypted=encrypted), bool(env_value), stored

    elevenlabs, elevenlabs_env, elevenlabs_stored = pick(
        "ELEVENLABS_API_KEY", settings.elevenlabs_api_key_enc
    )
    speechify, speechify_env, speechify_stored = pick(
        "SPEECHIFY_API_KEY", settings.speechify_api_key_enc
    )
    openrouter, openrouter_env, openrouter_stored = pick(
        "OPENROUTER_API_KEY", settings.openrouter_api_key_enc
    )
    openai, openai_env, openai_stored = pick("OPENAI_API_KEY", settings.openai_api_key_enc)
    anthropic, anthropic_env, anthropic_stored = pick(
        "ANTHROPIC_API_KEY", settings.anthropic_api_key_enc
    )
    llm_api_key, llm_env, llm_stored = pick("LLM_API_KEY", settings.llm_api_key_enc)

    env_base_url = env_str("LLM_BASE_URL")
    llm_base_url = env_base_url or (settings.llm_base_url.strip() or None)

    zyte, zyte_env, zyte_stored = pick("ZYTE_API_KEY", settings.zyte_api_key_enc)
    finnhub, finnhub_env, finnhub_stored = pick("FINNHUB_API_KEY", settings.finnhub_api_key_enc)
    newsdata, newsdata_env, newsdata_stored = pick(
        "NEWSDATA_API_KEY", settings.newsdata_api_key_enc
    )
    weatherapi, weatherapi_env, weatherapi_stored = pick(
        "WEATHERAPI_API_KEY", settings.weatherapi_api_key_enc
    )

    return Credentials(
        elevenlabs_api_key=elevenlabs,
        speechify_api_key=speechify,
        openrouter_api_key=openrouter,
        openai_api_key=openai,
        anthropic_api_key=anthropic,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        zyte_api_key=zyte,
        finnhub_api_key=finnhub,
        newsdata_api_key=newsdata,
        weatherapi_api_key=weatherapi,
        elevenlabs_from_env=elevenlabs_env,
        speechify_from_env=speechify_env,
        openrouter_from_env=openrouter_env,
        openai_from_env=openai_env,
        anthropic_from_env=anthropic_env,
        llm_from_env=llm_env,
        zyte_from_env=zyte_env,
        finnhub_from_env=finnhub_env,
        newsdata_from_env=newsdata_env,
        weatherapi_from_env=weatherapi_env,
        elevenlabs_stored=elevenlabs_stored,
        speechify_stored=speechify_stored,
        openrouter_stored=openrouter_stored,
        openai_stored=openai_stored,
        anthropic_stored=anthropic_stored,
        llm_stored=llm_stored,
        zyte_stored=zyte_stored,
        finnhub_stored=finnhub_stored,
        newsdata_stored=newsdata_stored,
        weatherapi_stored=weatherapi_stored,
    )


def import_env_secrets_if_empty(settings: Settings) -> bool:
    """Copy env API keys into the database when fields are empty (first boot / migration)."""

    changed = False
    for field_name, env_name in _SECRET_FIELDS:
        if secret_is_stored(getattr(settings, field_name)):
            continue
        env_value = env_str(env_name)
        if not env_value:
            continue
        setattr(settings, field_name, encrypt_secret(env_value))
        changed = True

    if not settings.llm_base_url.strip() and config.llm_base_url:
        settings.llm_base_url = config.llm_base_url.strip()
        changed = True

    return changed


def apply_secret_updates(
    settings: Settings,
    *,
    elevenlabs_api_key: str = "",
    speechify_api_key: str = "",
    openrouter_api_key: str = "",
    openai_api_key: str = "",
    anthropic_api_key: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    zyte_api_key: str = "",
    finnhub_api_key: str = "",
    newsdata_api_key: str = "",
    weatherapi_api_key: str = "",
    clear_elevenlabs: bool = False,
    clear_speechify: bool = False,
    clear_openrouter: bool = False,
    clear_openai: bool = False,
    clear_anthropic: bool = False,
    clear_llm: bool = False,
    clear_zyte: bool = False,
    clear_finnhub: bool = False,
    clear_newsdata: bool = False,
    clear_weatherapi: bool = False,
) -> None:
    updates: list[tuple[str, str, bool]] = [
        ("elevenlabs_api_key_enc", elevenlabs_api_key, clear_elevenlabs),
        ("speechify_api_key_enc", speechify_api_key, clear_speechify),
        ("openrouter_api_key_enc", openrouter_api_key, clear_openrouter),
        ("openai_api_key_enc", openai_api_key, clear_openai),
        ("anthropic_api_key_enc", anthropic_api_key, clear_anthropic),
        ("llm_api_key_enc", llm_api_key, clear_llm),
        ("zyte_api_key_enc", zyte_api_key, clear_zyte),
        ("finnhub_api_key_enc", finnhub_api_key, clear_finnhub),
        ("newsdata_api_key_enc", newsdata_api_key, clear_newsdata),
        ("weatherapi_api_key_enc", weatherapi_api_key, clear_weatherapi),
    ]

    for field_name, submitted_value, should_clear in updates:
        if should_clear:
            setattr(settings, field_name, "")
            continue
        if submitted_value.strip():
            setattr(settings, field_name, encrypt_secret(submitted_value))

    if llm_base_url.strip():
        settings.llm_base_url = llm_base_url.strip()
