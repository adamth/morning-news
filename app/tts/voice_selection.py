"""Voice selection helpers for TTS narration."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from .base import TtsProvider, TtsVoice

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedVoice:
    voice_id: str
    name: str

VOICE_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("", "Match news language"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
    ("ko", "Korean"),
    ("hi", "Hindi"),
    ("ar", "Arabic"),
]

FALLBACK_ACCENTS: list[str] = [
    "american",
    "british",
    "australian",
    "irish",
    "scottish",
    "indian",
    "canadian",
    "south african",
    "new zealand",
    "swedish",
    "italian",
    "german",
    "french",
    "spanish",
]


def resolve_voice_language(*, news_hl: str, voice_language: str) -> str:
    explicit = voice_language.strip().lower()
    if explicit:
        return explicit
    if news_hl.strip():
        return news_hl.strip().split("-", 1)[0].lower()
    return "en"


def display_voice_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        return "your host"
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0].strip()
    return cleaned or "your host"


def build_narrator_opening(voice_name: str, podcast_title: str) -> str:
    name = display_voice_name(voice_name)
    show = podcast_title.strip() or "Morning News"
    return f"This is {name} with {show}."


def pick_daily_voice(
    voices: list[TtsVoice],
    *,
    date_text: str,
    language: str,
    accent: str,
    fallback_voice_id: str,
    fallback_voice_name: str,
) -> ResolvedVoice:
    if not voices:
        return ResolvedVoice(voice_id=fallback_voice_id, name=fallback_voice_name)
    seed = f"{date_text}|{language}|{accent.strip().lower()}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    index = int(digest, 16) % len(voices)
    chosen = voices[index]
    return ResolvedVoice(voice_id=chosen.voice_id, name=chosen.name)


def resolve_episode_voice(
    provider: TtsProvider,
    *,
    voice_id: str,
    voice_randomize: bool,
    voice_language: str,
    voice_accent: str,
    news_hl: str,
    date_text: str,
) -> ResolvedVoice:
    fallback = provider.get_voice(voice_id)
    fallback_name = fallback.name if fallback else voice_id

    if not voice_randomize:
        return ResolvedVoice(voice_id=voice_id, name=fallback_name)

    language = resolve_voice_language(news_hl=news_hl, voice_language=voice_language)
    accent = voice_accent.strip().lower()

    library_voices = provider.list_voices_matching(language=language, accent=accent or None)
    if not library_voices and accent:
        library_voices = provider.list_voices_matching(language=language)

    resolved = pick_daily_voice(
        library_voices,
        date_text=date_text,
        language=language,
        accent=accent,
        fallback_voice_id=voice_id,
        fallback_voice_name=fallback_name,
    )
    if resolved.voice_id != voice_id:
        logger.info(
            "Daily narrator: %s (%s) — language=%s, accent=%s",
            display_voice_name(resolved.name),
            resolved.voice_id,
            language,
            accent or "any",
        )
    return resolved


def list_voice_options(
    provider: TtsProvider,
    *,
    voice_language: str,
    voice_accent: str,
    news_hl: str,
) -> list[TtsVoice]:
    """Voices for the settings dropdown, filtered when language or accent are set."""
    language = resolve_voice_language(news_hl=news_hl, voice_language=voice_language)
    accent = voice_accent.strip().lower()

    library_voices = provider.list_voices_matching(language=language, accent=accent or None)
    if library_voices:
        return library_voices

    account_voices = provider.list_voices()
    if accent:
        filtered = [voice for voice in account_voices if voice.accent.lower() == accent]
        return filtered or account_voices
    return account_voices


def list_accent_options(
    provider: TtsProvider,
    *,
    voice_language: str,
    news_hl: str,
) -> list[str]:
    language = resolve_voice_language(news_hl=news_hl, voice_language=voice_language)
    library_voices = provider.list_voices_matching(language=language)
    accents = {voice.accent.strip().lower() for voice in library_voices if voice.accent.strip()}
    accents.update(FALLBACK_ACCENTS)
    return sorted(accents)
