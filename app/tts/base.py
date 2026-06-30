"""Abstract text-to-speech provider interface so providers stay swappable."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TtsVoice:
    voice_id: str
    name: str
    description: str = ""
    accent: str = ""
    language: str = ""


class TtsProvider(abc.ABC):
    """A provider turns text into an mp3 file on disk."""

    @abc.abstractmethod
    def synthesize(self, text: str, output_path: Path, *, voice_id: str, model_id: str) -> Path:
        """Render `text` to an mp3 at `output_path` and return the path."""

    @abc.abstractmethod
    def list_voices(self) -> list[TtsVoice]:
        """Return the voices available to this account."""

    def list_voices_matching(
        self,
        *,
        language: str | None = None,
        accent: str | None = None,
    ) -> list[TtsVoice]:
        """Return library voices filtered by language and accent when supported."""
        voices = self.list_voices()
        if language:
            language = language.lower()
            voices = [voice for voice in voices if not voice.language or voice.language.lower() == language]
        if accent:
            accent = accent.lower()
            voices = [voice for voice in voices if not voice.accent or voice.accent.lower() == accent]
        return voices

    def get_voice(self, voice_id: str) -> TtsVoice | None:
        for voice in self.list_voices():
            if voice.voice_id == voice_id:
                return voice
        return None
