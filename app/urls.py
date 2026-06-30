"""Resolve the public base URL for RSS enclosures and UI links."""

from __future__ import annotations

from starlette.requests import Request

from .config import config


def resolve_base_url(request: Request) -> str:
    """Return the canonical public base URL for link generation.

    Uses ``BASE_URL`` when set; otherwise derives from the incoming request
    (``Host``, ``X-Forwarded-*`` when behind a reverse proxy).
    """

    if config.base_url:
        return config.base_url
    return str(request.base_url).rstrip("/")
