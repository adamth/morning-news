"""Token-protected episode audio serving."""

from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session

from ..config import config
from ..db import Episode, get_session, get_settings

router = APIRouter()

_DEFAULT_ARTWORK = Path(__file__).resolve().parent.parent / "static" / "podcast-artwork.png"


@router.get("/media/{episode_id}.mp3")
def episode_audio(
    episode_id: int,
    token: str = Query(""),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    if not token or not hmac.compare_digest(token, settings.feed_token):
        raise HTTPException(status_code=403, detail="Invalid token")

    episode = session.get(Episode, episode_id)
    if episode is None or not episode.audio_path:
        raise HTTPException(status_code=404, detail="Episode audio not found")

    audio_file = config.episodes_dir / episode.audio_path
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="Audio file missing")

    return FileResponse(
        audio_file,
        media_type="audio/mpeg",
        filename=f"morning-news-{episode_id}.mp3",
    )


@router.get("/podcast-artwork.png")
def podcast_artwork():
    artwork_file = config.artwork_path if config.artwork_path.exists() else _DEFAULT_ARTWORK
    if not artwork_file.exists():
        raise HTTPException(status_code=404, detail="Podcast artwork not found")

    return FileResponse(artwork_file, media_type="image/png")
