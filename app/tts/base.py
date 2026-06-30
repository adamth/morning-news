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


class TtsProvider(abc.ABC):
    """A provider turns text into an mp3 file on disk."""

    @abc.abstractmethod
    def synthesize(self, text: str, output_path: Path, *, voice_id: str, model_id: str) -> Path:
        """Render `text` to an mp3 at `output_path` and return the path."""

    @abc.abstractmethod
    def list_voices(self) -> list[TtsVoice]:
        """Return the voices available to this account."""
