"""TTS provider resolution — ElevenLabs or Speechify, chosen in Settings."""

from __future__ import annotations

from enum import Enum

from ..credentials import Credentials
from .base import TtsError, TtsProvider
from .elevenlabs import ElevenLabsProvider
from .speechify import SpeechifyProvider


class TtsProviderId(str, Enum):
    elevenlabs = "elevenlabs"
    speechify = "speechify"


TTS_PROVIDER_LABELS: dict[TtsProviderId, str] = {
    TtsProviderId.elevenlabs: "ElevenLabs",
    TtsProviderId.speechify: "Speechify",
}

DEFAULT_VOICE_MODELS: dict[TtsProviderId, str] = {
    TtsProviderId.elevenlabs: "eleven_v3",
    TtsProviderId.speechify: "simba-english",
}

DEFAULT_VOICE_IDS: dict[TtsProviderId, str] = {
    TtsProviderId.elevenlabs: "JBFqnCBsd6RMkjVDRZzb",  # George
    TtsProviderId.speechify: "george",
}

# (model id, label shown in the Voice quality dropdown)
VOICE_MODEL_OPTIONS: dict[TtsProviderId, list[tuple[str, str]]] = {
    TtsProviderId.elevenlabs: [
        ("eleven_v3", "Best quality"),
        ("eleven_multilingual_v2", "Multilingual"),
        ("eleven_turbo_v2_5", "Balanced"),
        ("eleven_flash_v2_5", "Fastest"),
    ],
    TtsProviderId.speechify: [
        ("simba-english", "Best quality (English)"),
        ("simba-multilingual", "Multilingual"),
    ],
}


def parse_tts_provider(value: str | None) -> TtsProviderId | None:
    if not value or not value.strip():
        return None
    try:
        return TtsProviderId(value.strip().lower())
    except ValueError:
        return None


def available_tts_providers(credentials: Credentials) -> list[TtsProviderId]:
    """Narration providers that have credentials configured."""

    providers: list[TtsProviderId] = []
    if credentials.elevenlabs_api_key:
        providers.append(TtsProviderId.elevenlabs)
    if credentials.speechify_api_key:
        providers.append(TtsProviderId.speechify)
    return providers


def resolve_tts_provider(
    *,
    credentials: Credentials,
    settings_provider: str = "",
) -> TtsProviderId:
    explicit = parse_tts_provider(settings_provider)
    if explicit is not None:
        return explicit
    configured = available_tts_providers(credentials)
    if configured:
        return configured[0]
    return TtsProviderId.elevenlabs


def tts_setup_hint(provider: TtsProviderId) -> str:
    return {
        TtsProviderId.elevenlabs: "Add your ElevenLabs API key in Settings → Connections",
        TtsProviderId.speechify: "Add your Speechify API key in Settings → Connections",
    }[provider]


def resolve_tts_api_key(provider: TtsProviderId, credentials: Credentials) -> str | None:
    if provider is TtsProviderId.elevenlabs:
        return credentials.elevenlabs_api_key
    if provider is TtsProviderId.speechify:
        return credentials.speechify_api_key
    return None


def normalize_voice_model(provider: TtsProviderId, model: str) -> str:
    """A model saved for one provider means nothing to the other — fall back to the default."""

    cleaned = (model or "").strip()
    known = {model_id for model_id, _ in VOICE_MODEL_OPTIONS[provider]}
    if cleaned in known:
        return cleaned
    return DEFAULT_VOICE_MODELS[provider]


def get_provider(
    *,
    credentials: Credentials,
    settings_provider: str = "",
) -> TtsProvider:
    provider = resolve_tts_provider(credentials=credentials, settings_provider=settings_provider)
    api_key = resolve_tts_api_key(provider, credentials)
    if not api_key:
        raise TtsError(tts_setup_hint(provider))
    if provider is TtsProviderId.speechify:
        return SpeechifyProvider(api_key)
    return ElevenLabsProvider(api_key)
