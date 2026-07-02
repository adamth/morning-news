"""Shared HTTP retry helpers for rate-limited upstream APIs."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUS_CODES = frozenset({429, 503})
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY_SECONDS = 1.0


def retry_after_seconds(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return max(float(header), 0.0)
    except ValueError:
        return None


def httpx_request_with_retry(
    request: Callable[[], httpx.Response],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    retry_status_codes: frozenset[int] = DEFAULT_RETRY_STATUS_CODES,
) -> httpx.Response:
    """Run an httpx request, backing off when upstream returns 429/503."""

    last_response: httpx.Response | None = None
    for attempt in range(1, max_attempts + 1):
        response = request()
        if response.status_code not in retry_status_codes:
            return response
        last_response = response
        if attempt >= max_attempts:
            break
        delay = retry_after_seconds(response) or (base_delay_seconds * (2 ** (attempt - 1)))
        sleep_for = delay + random.uniform(0, 0.25 * delay)
        logger.info(
            "HTTP %s from %s — retrying in %.1fs (attempt %d/%d)",
            response.status_code,
            response.request.url,
            sleep_for,
            attempt,
            max_attempts,
        )
        time.sleep(sleep_for)
    assert last_response is not None
    return last_response
