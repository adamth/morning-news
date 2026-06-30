"""Text-to-speech providers."""

from .base import TtsProvider, TtsVoice
from .elevenlabs import ElevenLabsProvider, get_provider
from .voice_selection import (
    ResolvedVoice,
    VOICE_LANGUAGE_OPTIONS,
    build_narrator_opening,
    list_accent_options,
    list_voice_options,
    resolve_episode_voice,
    resolve_voice_language,
)

__all__ = [
    "TtsProvider",
    "TtsVoice",
    "ResolvedVoice",
    "ElevenLabsProvider",
    "get_provider",
    "VOICE_LANGUAGE_OPTIONS",
    "build_narrator_opening",
    "list_accent_options",
    "list_voice_options",
    "resolve_episode_voice",
    "resolve_voice_language",
]
