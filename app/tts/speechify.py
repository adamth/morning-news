"""Speechify text-to-speech provider (simple pricing, generous free tier)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from ..http_retry import httpx_request_with_retry
from .base import TtsError, TtsProvider, TtsVoice

logger = logging.getLogger(__name__)

# Speechify emotion presets — applied via SSML on synthesis.
# https://docs.sws.speechify.com/text-to-speech/features/emotion-control
SPEECHIFY_EMOTION_OPTIONS: list[tuple[str, str]] = [
    ("", "Natural"),
    ("calm", "Calm"),
    ("warm", "Warm"),
    ("cheerful", "Cheerful"),
    ("bright", "Bright"),
    ("energetic", "Energetic"),
    ("assertive", "Assertive"),
    ("direct", "Direct"),
    ("relaxed", "Relaxed"),
    ("surprised", "Surprised"),
    ("sad", "Sad"),
    ("fearful", "Fearful"),
    ("angry", "Angry"),
    ("terrified", "Terrified"),
]
SPEECHIFY_EMOTION_IDS = {emotion for emotion, _ in SPEECHIFY_EMOTION_OPTIONS if emotion}

# Speechify rate-limits /v1/voices hard, and one settings-page render asks for
# the catalog more than once — cache it per key for a few minutes.
_VOICES_CACHE_TTL = 300.0
_voices_cache: dict[str, tuple[float, list[TtsVoice]]] = {}

API_BASE = "https://api.speechify.ai"
_SYNTH_TIMEOUT = 300.0
_LIST_TIMEOUT = 15.0

# /v1/audio/stream accepts up to 20,000 characters per request; longer
# narrations are split on paragraph boundaries and the audio concatenated.
_MAX_INPUT_CHARS = 19_000

# Speechify voices carry a locale (en-US); the app filters by ElevenLabs-style
# accent labels, so map the common English regions onto those.
_ACCENT_BY_REGION = {
    "US": "american",
    "GB": "british",
    "AU": "australian",
    "IE": "irish",
    "IN": "indian",
    "CA": "canadian",
    "ZA": "south african",
    "NZ": "new zealand",
    "SCT": "scottish",
}


def _split_locale(locale: str) -> tuple[str, str]:
    """('en-US') -> ('en', 'american'); unknown regions keep an empty accent."""
    cleaned = (locale or "").strip()
    if not cleaned:
        return "", ""
    parts = cleaned.replace("_", "-").split("-", 1)
    language = parts[0].lower()
    accent = ""
    if language == "en" and len(parts) == 2:
        accent = _ACCENT_BY_REGION.get(parts[1].upper(), "")
    return language, accent


def _chunk_text(text: str, limit: int) -> list[str]:
    """Split on blank lines (then hard-split) so each chunk fits the API limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def normalize_speechify_emotion(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in SPEECHIFY_EMOTION_IDS:
        return cleaned
    return ""


def apply_speechify_emotion(text: str, emotion: str) -> str:
    cleaned = normalize_speechify_emotion(emotion)
    if not cleaned:
        return text
    return (
        f'<speak><speechify:style emotion="{cleaned}">'
        f"{escape(text)}</speechify:style></speak>"
    )


class SpeechifyProvider(TtsProvider):
    lists_full_catalog = True

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice_id: str,
        model_id: str,
        emotion: str = "",
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as handle:
            for chunk in _chunk_text(text, _MAX_INPUT_CHARS):
                styled = apply_speechify_emotion(chunk, emotion)
                handle.write(self._synthesize_chunk(styled, voice_id=voice_id, model_id=model_id))
        return output_path

    def _synthesize_chunk(self, text: str, *, voice_id: str, model_id: str) -> bytes:
        try:
            response = httpx_request_with_retry(
                lambda: httpx.post(
                    f"{API_BASE}/v1/audio/stream",
                    headers={**self._headers(), "Accept": "audio/mpeg"},
                    json={"input": text, "voice_id": voice_id, "model": model_id},
                    timeout=_SYNTH_TIMEOUT,
                )
            )
        except httpx.HTTPError as error:
            raise TtsError(f"Could not reach Speechify: {error}") from error
        if response.status_code == 401:
            raise TtsError("Speechify API key was rejected — update it in Settings → Connections")
        if response.status_code >= 400:
            raise TtsError(
                f"Speechify returned HTTP {response.status_code}: {response.text[:300]}"
            )
        return response.content

    def list_voices(self) -> list[TtsVoice]:
        cached = _voices_cache.get(self._api_key)
        if cached is not None and time.monotonic() - cached[0] < _VOICES_CACHE_TTL:
            return cached[1]
        voices: list[TtsVoice] = []
        cursor: str | None = None
        try:
            # /v1/voices returns {"voices": [...], "next_cursor": ..., "has_more": ...}
            # (currently a single page; follow the cursor in case that changes).
            while True:
                response = httpx_request_with_retry(
                    lambda cursor=cursor: httpx.get(
                        f"{API_BASE}/v1/voices",
                        headers=self._headers(),
                        params={"cursor": cursor} if cursor else None,
                        timeout=_LIST_TIMEOUT,
                    )
                )
                response.raise_for_status()
                payload = response.json()
                page = payload.get("voices", []) if isinstance(payload, dict) else payload
                voices.extend(self._parse_voice(voice) for voice in page or [])
                cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
                if not isinstance(payload, dict) or not payload.get("has_more") or not cursor:
                    break
        except (httpx.HTTPError, ValueError, AttributeError) as error:
            logger.warning("Could not list Speechify voices: %s", error)
            # Serve a stale catalog rather than nothing (e.g. on a 429).
            return cached[1] if cached is not None else []
        result = [voice for voice in voices if voice is not None]
        _voices_cache[self._api_key] = (time.monotonic(), result)
        return result

    @staticmethod
    def _parse_preview(voice: dict) -> str:
        preview = (voice.get("preview_audio") or "").strip()
        if preview:
            return preview
        for model in voice.get("models") or []:
            if not isinstance(model, dict):
                continue
            for language in model.get("languages") or []:
                if not isinstance(language, dict):
                    continue
                language_preview = (language.get("preview_audio") or "").strip()
                if language_preview:
                    return language_preview
        return ""

    @staticmethod
    def _parse_voice(voice: dict) -> TtsVoice | None:
        if not isinstance(voice, dict):
            return None
        voice_id = voice.get("id") or ""
        if not voice_id:
            return None
        language, accent = _split_locale(voice.get("locale") or "")
        gender = (voice.get("gender") or "").strip().lower()
        return TtsVoice(
            voice_id=voice_id,
            name=voice.get("display_name") or voice_id,
            description=gender,
            accent=accent,
            language=language,
            preview_url=SpeechifyProvider._parse_preview(voice),
        )
