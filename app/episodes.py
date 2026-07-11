"""Episode lifecycle helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, select

from .config import config
from .db import (
    Episode,
    EpisodeArticle,
    EpisodeLogEntry,
    EpisodeStatus,
    Message,
    MessageStatus,
)

logger = logging.getLogger(__name__)


class EpisodeDeleteError(ValueError):
    """Raised when an episode cannot be deleted."""


def delete_episode(session: Session, episode_id: int) -> None:
    """Remove an episode and all related records so its stories can air again."""

    episode = session.get(Episode, episode_id)
    if episode is None:
        raise EpisodeDeleteError("Episode not found")

    if episode.status is EpisodeStatus.generating:
        raise EpisodeDeleteError("Cannot delete an episode while it is being generated")

    for entry in session.exec(
        select(EpisodeLogEntry).where(EpisodeLogEntry.episode_id == episode_id)
    ).all():
        session.delete(entry)

    for article in session.exec(
        select(EpisodeArticle).where(EpisodeArticle.episode_id == episode_id)
    ).all():
        session.delete(article)

    for message in session.exec(
        select(Message).where(Message.episode_id == episode_id)
    ).all():
        message.status = MessageStatus.pending
        message.episode_id = None
        message.resolved_at = None
        session.add(message)

    _delete_episode_files(episode_id, episode.audio_path)

    session.delete(episode)
    session.commit()


def _delete_episode_files(episode_id: int, audio_path: str | None) -> None:
    episodes_dir = config.episodes_dir
    candidates: list[Path] = [
        episodes_dir / f"{episode_id}.mp3",
        episodes_dir / f"{episode_id}.voice.mp3",
        episodes_dir / f"{episode_id}.fast.mp3",
    ]
    if audio_path:
        candidates.append(episodes_dir / audio_path)

    for path in candidates:
        try:
            if path.is_file():
                path.unlink()
        except OSError as error:
            logger.warning("Failed to delete episode file %s: %s", path, error)
