"""Audio assembly via ffmpeg: optional intro/outro music + loudness normalization."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# EBU R128 targets suitable for spoken-word podcasts.
_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
_STEREO = "aresample=44100,aformat=channel_layouts=stereo"
# libmp3lame expects 1152-sample frames; amix/adelay can emit misaligned buffers.
_MIX_OUTPUT = "aformat=sample_fmts=fltp:channel_layouts=stereo,asetnsamples=n=1152"

# Playback speed for narration only (1.0 = normal). Applied via ffmpeg atempo after TTS.
NARRATION_SPEED = 1


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

    if intro_duration <= 0:
        return _STEREO

    full_volume_seconds = max(0.0, min(play_seconds, intro_duration))
    fade_seconds = intro_duration - full_volume_seconds
    if fade_seconds <= 0.05:
        return _STEREO

    return f"{_STEREO},afade=t=out:st={full_volume_seconds:.3f}:d={fade_seconds:.3f}"


def _voice_delay_filter(play_seconds: float) -> str:
    """Delay narration so it starts when the intro fade begins."""

    delay_ms = int(max(0.0, play_seconds) * 1000)
    if delay_ms <= 0:
        return _STEREO
    return f"{_STEREO},adelay={delay_ms}|{delay_ms}"


def _outro_filter_chain(outro_duration: float, overlap_seconds: float, voice_duration: float) -> str:
    """Delay outro so it starts ``overlap_seconds`` before the narration ends."""

    overlap = max(0.0, min(overlap_seconds, outro_duration, voice_duration))
    delay_seconds = max(0.0, voice_duration - overlap)
    delay_ms = int(delay_seconds * 1000)
    if delay_ms <= 0:
        return _STEREO
    return f"{_STEREO},adelay={delay_ms}|{delay_ms}"


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg failed: %s", result.stderr[-2000:])
        raise AudioError("ffmpeg failed to assemble the episode")


def _encode_mp3(ffmpeg: str, output_mp3: Path, *, inputs: list[Path], filter_complex: str | None, audio_filter: str | None) -> None:
    command = [ffmpeg, "-y", *[arg for path in inputs for arg in ("-i", str(path))]]
    if filter_complex is not None:
        command.extend(["-filter_complex", filter_complex, "-map", "[out]"])
    elif audio_filter is not None:
        command.extend(["-af", audio_filter])
    command.extend(["-c:a", "libmp3lame", "-b:a", "128k", str(output_mp3)])
    _run_ffmpeg(command)


def _mix_intro(voice_mp3: Path, intro_mp3: Path, output_mp3: Path, intro_play_seconds: float) -> None:
    ffmpeg = _require_ffmpeg()
    intro_duration = probe_duration(intro_mp3) or 0.0
    intro_filter = _intro_audio_filter(intro_duration, intro_play_seconds)
    voice_filter = _voice_delay_filter(intro_play_seconds)
    filter_complex = (
        f"[0:a]{intro_filter}[intro];"
        f"[1:a]{voice_filter}[voice];"
        f"[intro][voice]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,{_MIX_OUTPUT}[out]"
    )
    _encode_mp3(ffmpeg, output_mp3, inputs=[intro_mp3, voice_mp3], filter_complex=filter_complex, audio_filter=None)


def _mix_outro(voice_mp3: Path, outro_mp3: Path, output_mp3: Path, outro_play_seconds: float) -> None:
    ffmpeg = _require_ffmpeg()
    voice_duration = probe_duration(voice_mp3) or 0.0
    outro_duration = probe_duration(outro_mp3) or 0.0
    outro_chain = _outro_filter_chain(outro_duration, outro_play_seconds, voice_duration)
    filter_complex = (
        f"[0:a]{_STEREO}[voice];"
        f"[1:a]{outro_chain}[outro];"
        f"[voice][outro]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,{_MIX_OUTPUT}[out]"
    )
    _encode_mp3(ffmpeg, output_mp3, inputs=[voice_mp3, outro_mp3], filter_complex=filter_complex, audio_filter=None)


def _normalize(input_mp3: Path, output_mp3: Path) -> None:
    ffmpeg = _require_ffmpeg()
    _encode_mp3(ffmpeg, output_mp3, inputs=[input_mp3], filter_complex=None, audio_filter=_LOUDNORM)


def assemble_episode(
    voice_mp3: Path,
    output_mp3: Path,
    intro_mp3: Path | None = None,
    intro_play_seconds: float = 6.0,
    outro_mp3: Path | None = None,
    outro_play_seconds: float = 2.0,
) -> Path:
    """Combine optional intro/outro music with narration into a normalized mp3.

    Intro plays alone for ``intro_play_seconds``, then narration begins while
    the intro fades out over the remainder of the intro file.

    Outro starts ``outro_play_seconds`` before the narration ends (mixed together),
    then continues alone for the remainder of the outro file.
    """

    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    has_intro = intro_mp3 is not None and intro_mp3.exists()
    has_outro = outro_mp3 is not None and outro_mp3.exists()

    if not has_intro and not has_outro:
        _normalize(voice_mp3, output_mp3)
        return output_mp3

    work_path = voice_mp3
    intro_temp: Path | None = None

    if has_intro:
        intro_temp = output_mp3.with_suffix(".intro-tmp.mp3")
        _mix_intro(work_path, intro_mp3, intro_temp, intro_play_seconds)
        work_path = intro_temp

    if has_outro:
        outro_temp = output_mp3.with_suffix(".outro-tmp.mp3")
        _mix_outro(work_path, outro_mp3, outro_temp, outro_play_seconds)
        _normalize(outro_temp, output_mp3)
        outro_temp.unlink(missing_ok=True)
    elif intro_temp is not None:
        _normalize(intro_temp, output_mp3)

    if intro_temp is not None:
        intro_temp.unlink(missing_ok=True)

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
