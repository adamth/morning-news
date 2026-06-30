"""OpenRouter model listing for the settings UI."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from .config import config

logger = logging.getLogger(__name__)

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 3600

# Sensible defaults for script writing; shown first in the picker.
RECOMMENDED_MODEL_IDS: tuple[str, ...] = (
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.5-flash-preview",
    "google/gemini-2.0-flash-001",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat",
)


@dataclass
class OpenRouterModel:
    id: str
    name: str
    context_length: int | None = None
    recommended: bool = False

    @property
    def label(self) -> str:
        if self.name and self.name != self.id:
            return f"{self.name} ({self.id})"
        return self.id


_models_cache: tuple[float, list[OpenRouterModel]] | None = None


def _is_chat_model(entry: dict) -> bool:
    architecture = entry.get("architecture") or {}
    output_modalities = architecture.get("output_modalities") or []
    return "text" in output_modalities


def _fetch_models() -> list[OpenRouterModel]:
    headers: dict[str, str] = {}
    if config.openrouter_api_key:
        headers["Authorization"] = f"Bearer {config.openrouter_api_key}"

    try:
        response = httpx.get(MODELS_URL, headers=headers, timeout=25)
        response.raise_for_status()
        entries = response.json().get("data") or []
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Could not fetch OpenRouter models: %s", error)
        return []

    models: list[OpenRouterModel] = []
    for entry in entries:
        if not _is_chat_model(entry):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        models.append(
            OpenRouterModel(
                id=model_id,
                name=(entry.get("name") or model_id).strip(),
                context_length=entry.get("context_length"),
                recommended=model_id in RECOMMENDED_MODEL_IDS,
            )
        )

    recommended_rank = {model_id: index for index, model_id in enumerate(RECOMMENDED_MODEL_IDS)}
    models.sort(
        key=lambda model: (
            recommended_rank.get(model.id, len(RECOMMENDED_MODEL_IDS)),
            model.name.lower(),
        )
    )
    return models


def list_chat_models(*, force_refresh: bool = False) -> list[OpenRouterModel]:
    """Return chat-capable OpenRouter models, with a simple in-memory cache."""

    global _models_cache
    now = time.time()
    if (
        not force_refresh
        and _models_cache is not None
        and now - _models_cache[0] < CACHE_TTL_SECONDS
    ):
        return _models_cache[1]

    models = _fetch_models()
    if models:
        _models_cache = (now, models)
    return models
