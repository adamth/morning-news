"""Public (token-guarded) podcast RSS feed."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlmodel import Session, select

from ..config import config
from ..db import Episode, EpisodeArticle, EpisodeStatus, get_session, get_settings
from ..feed import build_feed
from ..urls import resolve_base_url

router = APIRouter()


def _check_token(token: str, expected: str) -> None:
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid feed token")


@router.get("/feed.xml")
def podcast_feed(
    request: Request,
    token: str = Query(""),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    _check_token(token, settings.feed_token)

    episodes = session.exec(
        select(Episode)
        .where(Episode.status == EpisodeStatus.ready)
        .order_by(Episode.created_at.desc())
        .limit(50)
    ).all()

    enriched: list[tuple[Episode, list[EpisodeArticle], int]] = []
    for episode in episodes:
        if not episode.audio_path:
            continue
        audio_file = config.episodes_dir / episode.audio_path
        if not audio_file.exists():
            continue
        articles = session.exec(
            select(EpisodeArticle).where(EpisodeArticle.episode_id == episode.id)
        ).all()
        enriched.append((episode, articles, audio_file.stat().st_size))

    xml = build_feed(settings, enriched, resolve_base_url(request))
    return Response(content=xml, media_type="application/rss+xml")
