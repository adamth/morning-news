"""ElevenLabs text-to-speech provider (most realistic voices)."""

from __future__ import annotations

import logging
from pathlib import Path

from .base import TtsProvider, TtsVoice

logger = logging.getLogger(__name__)


class ElevenLabsProvider(TtsProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from elevenlabs.client import ElevenLabs

            self._client = ElevenLabs(api_key=self._api_key)
        return self._client

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice_id: str,
        model_id: str,
        emotion: str = "",
    ) -> Path:
        # mp3_44100_128 is a good quality/size balance for spoken word.
        audio = self.client.text_to_speech.convert(
            voice_id=voice_id,
            model_id=model_id,
            output_format="mp3_44100_128",
            text=text,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as handle:
            for chunk in audio:
                if chunk:
                    handle.write(chunk)
        return output_path

    def list_voices(self) -> list[TtsVoice]:
        try:
            response = self.client.voices.get_all()
        except Exception as error:  # network/auth issues
            logger.warning("Could not list ElevenLabs voices: %s", error)
            return []
        voices: list[TtsVoice] = []
        for voice in getattr(response, "voices", []) or []:
            labels = getattr(voice, "labels", None) or {}
            voices.append(
                TtsVoice(
                    voice_id=voice.voice_id,
                    name=voice.name or voice.voice_id,
                    description=(getattr(voice, "category", "") or ""),
                    accent=(labels.get("accent") or ""),
                    language=(labels.get("language") or ""),
                )
            )
        return voices

    def list_voices_matching(
        self,
        *,
        language: str | None = None,
        accent: str | None = None,
    ) -> list[TtsVoice]:
        try:
            response = self.client.voices.get_shared(
                page_size=100,
                language=language,
                accent=accent,
            )
        except Exception as error:
            logger.warning("Could not list ElevenLabs library voices: %s", error)
            return super().list_voices_matching(language=language, accent=accent)
        voices: list[TtsVoice] = []
        for voice in getattr(response, "voices", []) or []:
            voices.append(
                TtsVoice(
                    voice_id=voice.voice_id,
                    name=voice.name or voice.voice_id,
                    description=voice.description or "",
                    accent=voice.accent or "",
                    language=voice.language or "",
                )
            )
        return voices

    def get_voice(self, voice_id: str) -> TtsVoice | None:
        try:
            voice = self.client.voices.get(voice_id=voice_id)
        except Exception as error:
            logger.warning("Could not fetch ElevenLabs voice %s: %s", voice_id, error)
            return super().get_voice(voice_id)
        labels = getattr(voice, "labels", None) or {}
        return TtsVoice(
            voice_id=voice.voice_id,
            name=voice.name or voice.voice_id,
            description=(getattr(voice, "category", "") or ""),
            accent=(labels.get("accent") or ""),
            language=(labels.get("language") or ""),
        )
