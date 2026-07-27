"""Episode audio serving."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import config
from ..db import Episode, EpisodeStatus, get_session

router = APIRouter()

_DEFAULT_ARTWORK = Path(__file__).resolve().parent.parent / "static" / "podcast-artwork.png"


def _serve_episode(episode: Episode | None) -> FileResponse:
    if episode is None or not episode.audio_path:
        raise HTTPException(status_code=404, detail="Episode audio not found")

    audio_file = config.episodes_dir / episode.audio_path
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="Audio file missing")

    return FileResponse(
        audio_file,
        media_type="audio/mpeg",
        filename=f"morning-news-{episode.id}.mp3",
    )


@router.get("/media/latest.mp3")
def latest_episode_audio(session: Session = Depends(get_session)):
    episode = session.exec(
        select(Episode)
        .where(Episode.status == EpisodeStatus.ready)
        .order_by(Episode.created_at.desc())
        .limit(1)
    ).first()
    return _serve_episode(episode)


@router.get("/media/{episode_id}.mp3")
def episode_audio(
    episode_id: int,
    session: Session = Depends(get_session),
):
    return _serve_episode(session.get(Episode, episode_id))


@router.get("/podcast-artwork.png")
def podcast_artwork():
    artwork_file = config.artwork_path if config.artwork_path.exists() else _DEFAULT_ARTWORK
    if not artwork_file.exists():
        raise HTTPException(status_code=404, detail="Podcast artwork not found")

    return FileResponse(artwork_file, media_type="image/png")
