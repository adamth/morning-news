"""Audio assembly via ffmpeg: optional intro music + loudness normalization."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# EBU R128 targets suitable for spoken-word podcasts.
_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"

# Playback speed for narration only (1.0 = normal). Applied via ffmpeg atempo after TTS.
NARRATION_SPEED = 1.1


class AudioError(RuntimeError):
    pass


def _require_ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise AudioError("ffmpeg not found on PATH")
    return binary


def speed_up_narration(input_mp3: Path, speed: float = NARRATION_SPEED) -> Path:
    """Increase narration playback speed slightly without changing pitch."""

    if abs(speed - 1.0) < 0.01:
        return input_mp3

    ffmpeg = _require_ffmpeg()
    temp_path = input_mp3.with_suffix(".fast.mp3")
    command = [
        ffmpeg, "-y",
        "-i", str(input_mp3),
        "-filter:a", f"atempo={speed}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(temp_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("ffmpeg atempo failed, using original speed: %s", result.stderr[-500:])
        return input_mp3
    temp_path.replace(input_mp3)
    return input_mp3


def _intro_audio_filter(intro_duration: float, play_seconds: float) -> str:
    """Resample intro audio and fade out over the remaining file length."""

    base = "aresample=44100,aformat=channel_layouts=stereo"
    if intro_duration <= 0:
        return base

    full_volume_seconds = max(0.0, min(play_seconds, intro_duration))
    fade_seconds = intro_duration - full_volume_seconds
    if fade_seconds <= 0.05:
        return base

    return f"{base},afade=t=out:st={full_volume_seconds:.3f}:d={fade_seconds:.3f}"


def _voice_delay_filter(play_seconds: float) -> str:
    """Delay narration so it starts when the intro fade begins."""

    delay_ms = int(max(0.0, play_seconds) * 1000)
    base = "aresample=44100,aformat=channel_layouts=stereo"
    if delay_ms <= 0:
        return base
    return f"{base},adelay={delay_ms}|{delay_ms}"


def assemble_episode(
    voice_mp3: Path,
    output_mp3: Path,
    intro_mp3: Path | None = None,
    intro_play_seconds: float = 6.0,
) -> Path:
    """Combine optional intro music with the narration into a normalized mp3.

    Intro plays alone for ``intro_play_seconds``, then narration begins while
    the intro fades out over the remainder of the intro file.
    """

    ffmpeg = _require_ffmpeg()
    output_mp3.parent.mkdir(parents=True, exist_ok=True)

    if intro_mp3 is not None and intro_mp3.exists():
        intro_duration = probe_duration(intro_mp3) or 0.0
        intro_filter = _intro_audio_filter(intro_duration, intro_play_seconds)
        voice_filter = _voice_delay_filter(intro_play_seconds)
        filter_complex = (
            f"[0:a]{intro_filter}[intro];"
            f"[1:a]{voice_filter}[voice];"
            "[intro][voice]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mixed];"
            f"[mixed]{_LOUDNORM}[out]"
        )
        command = [
            ffmpeg, "-y",
            "-i", str(intro_mp3),
            "-i", str(voice_mp3),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "libmp3lame", "-b:a", "128k",
            str(output_mp3),
        ]
    else:
        command = [
            ffmpeg, "-y",
            "-i", str(voice_mp3),
            "-af", _LOUDNORM,
            "-c:a", "libmp3lame", "-b:a", "128k",
            str(output_mp3),
        ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg failed: %s", result.stderr[-2000:])
        raise AudioError("ffmpeg failed to assemble the episode")
    return output_mp3


def probe_duration(path: Path) -> float | None:
    """Return the duration of an audio file in seconds, if ffprobe is available."""

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    command = [
        ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
