"""Episode generation audit log — captures external calls and AI I/O for review."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator

from sqlmodel import Session

from .db import EpisodeLogEntry, utcnow

_current: ContextVar[EpisodeAuditLog | None] = ContextVar("episode_audit_log", default=None)

CATEGORY_LABELS: dict[str, str] = {
    "news": "News sources",
    "weather": "Weather forecast",
    "stocks": "Stock watchlist",
    "calendar": "Calendar",
    "messages": "Private messages",
    "llm": "AI generation",
    "tts": "Voice synthesis",
    "audio": "Audio assembly",
    "pipeline": "Pipeline",
}

def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace("_", " ").title())


def active_log() -> EpisodeAuditLog | None:
    return _current.get()


@dataclass
class LogTimer:
    started_at: float

    @classmethod
    def start(cls) -> LogTimer:
        return cls(started_at=time.perf_counter())

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started_at) * 1000, 1)


class EpisodeAuditLog:
    """Collects ordered audit entries for one episode generation run."""

    def __init__(self, session: Session, episode_id: int) -> None:
        self._session = session
        self._episode_id = episode_id
        self._sequence = 0
        self._lock = threading.Lock()

    def record(
        self,
        category: str,
        operation: str,
        *,
        status: str = "success",
        summary: str = "",
        request: Any = None,
        response: Any = None,
        duration_ms: float | None = None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        self._session.add(
            EpisodeLogEntry(
                episode_id=self._episode_id,
                category=category,
                operation=operation,
                status=status,
                summary=summary,
                request_data=_serialize(request),
                response_data=_serialize(response),
                duration_ms=duration_ms,
                sequence=sequence,
                created_at=utcnow(),
            )
        )

    def flush(self) -> None:
        self._session.commit()


@contextmanager
def episode_audit_log(session: Session, episode_id: int) -> Iterator[EpisodeAuditLog]:
    audit = EpisodeAuditLog(session, episode_id)
    token = _current.set(audit)
    try:
        yield audit
    finally:
        _current.reset(token)


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, default=str, indent=2)
    except (TypeError, ValueError):
        return str(value)
