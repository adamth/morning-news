"""Text-to-speech providers."""

from .base import TtsError, TtsProvider, TtsVoice
from .elevenlabs import ElevenLabsProvider
from .providers import (
    DEFAULT_VOICE_IDS,
    DEFAULT_VOICE_MODELS,
    TTS_PROVIDER_LABELS,
    VOICE_MODEL_OPTIONS,
    TtsProviderId,
    available_tts_providers,
    get_provider,
    normalize_voice_model,
    parse_tts_provider,
    resolve_tts_provider,
    tts_setup_hint,
)
from .speechify import (
    SPEECHIFY_EMOTION_OPTIONS,
    SpeechifyProvider,
    normalize_speechify_emotion,
)
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
    "TtsError",
    "TtsProvider",
    "TtsVoice",
    "ResolvedVoice",
    "ElevenLabsProvider",
    "SpeechifyProvider",
    "SPEECHIFY_EMOTION_OPTIONS",
    "normalize_speechify_emotion",
    "TtsProviderId",
    "TTS_PROVIDER_LABELS",
    "DEFAULT_VOICE_IDS",
    "DEFAULT_VOICE_MODELS",
    "VOICE_MODEL_OPTIONS",
    "available_tts_providers",
    "get_provider",
    "normalize_voice_model",
    "parse_tts_provider",
    "resolve_tts_provider",
    "tts_setup_hint",
    "VOICE_LANGUAGE_OPTIONS",
    "build_narrator_opening",
    "list_accent_options",
    "list_voice_options",
    "resolve_episode_voice",
    "resolve_voice_language",
]
