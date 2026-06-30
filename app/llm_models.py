"""Model catalogs for each LLM provider (settings UI autocomplete)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from .config import config
from .credentials import Credentials
from .llm_providers import LlmProviderId, resolve_api_key

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"

OPENROUTER_RECOMMENDED: tuple[str, ...] = (
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

OPENAI_RECOMMENDED: tuple[str, ...] = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4.1-nano",
    "o4-mini",
)

ANTHROPIC_RECOMMENDED: tuple[str, ...] = (
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
)


@dataclass
class LlmModelOption:
    id: str
    name: str
    recommended: bool = False

    @property
    def label(self) -> str:
        if self.name and self.name != self.id:
            return f"{self.name} ({self.id})"
        return self.id


_models_cache: dict[str, tuple[float, list[LlmModelOption]]] = {}


def _sort_models(models: list[LlmModelOption], recommended_ids: tuple[str, ...]) -> list[LlmModelOption]:
    recommended_rank = {model_id: index for index, model_id in enumerate(recommended_ids)}
    return sorted(
        models,
        key=lambda model: (
            recommended_rank.get(model.id, len(recommended_ids)),
            model.name.lower(),
        ),
    )


def _static_models(ids: tuple[str, ...]) -> list[LlmModelOption]:
    return [
        LlmModelOption(id=model_id, name=model_id, recommended=True)
        for model_id in ids
    ]


def _fetch_openrouter_models(credentials: Credentials) -> list[LlmModelOption]:
    headers: dict[str, str] = {}
    api_key = resolve_api_key(LlmProviderId.openrouter, credentials)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.get(OPENROUTER_MODELS_URL, headers=headers, timeout=25)
        response.raise_for_status()
        entries = response.json().get("data") or []
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Could not fetch OpenRouter models: %s", error)
        return _static_models(OPENROUTER_RECOMMENDED)

    models: list[LlmModelOption] = []
    for entry in entries:
        architecture = entry.get("architecture") or {}
        output_modalities = architecture.get("output_modalities") or []
        if "text" not in output_modalities:
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        models.append(
            LlmModelOption(
                id=model_id,
                name=(entry.get("name") or model_id).strip(),
                recommended=model_id in OPENROUTER_RECOMMENDED,
            )
        )
    return _sort_models(models, OPENROUTER_RECOMMENDED) if models else _static_models(OPENROUTER_RECOMMENDED)


def _fetch_openai_models(credentials: Credentials) -> list[LlmModelOption]:
    api_key = resolve_api_key(LlmProviderId.openai, credentials)
    if not api_key:
        return _static_models(OPENAI_RECOMMENDED)

    try:
        response = httpx.get(
            OPENAI_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=25,
        )
        response.raise_for_status()
        entries = response.json().get("data") or []
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Could not fetch OpenAI models: %s", error)
        return _static_models(OPENAI_RECOMMENDED)

    models: list[LlmModelOption] = []
    for entry in entries:
        model_id = entry.get("id")
        if not model_id or not any(token in model_id for token in ("gpt", "o1", "o3", "o4")):
            continue
        models.append(
            LlmModelOption(
                id=model_id,
                name=model_id,
                recommended=model_id in OPENAI_RECOMMENDED,
            )
        )
    return _sort_models(models, OPENAI_RECOMMENDED) if models else _static_models(OPENAI_RECOMMENDED)


def list_chat_models(
    provider: LlmProviderId | str = LlmProviderId.openrouter,
    *,
    credentials: Credentials,
    force_refresh: bool = False,
) -> list[LlmModelOption]:
    """Return chat models for the given provider, with a simple in-memory cache."""

    if isinstance(provider, str):
        provider = LlmProviderId(provider)

    cache_key = provider.value
    now = time.time()
    cached = _models_cache.get(cache_key)
    if not force_refresh and cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    if provider is LlmProviderId.openrouter:
        models = _fetch_openrouter_models(credentials)
    elif provider is LlmProviderId.openai:
        models = _fetch_openai_models(credentials)
    elif provider is LlmProviderId.anthropic:
        models = _static_models(ANTHROPIC_RECOMMENDED)
    else:
        models = _static_models(OPENAI_RECOMMENDED)

    if models:
        _models_cache[cache_key] = (now, models)
    return models
