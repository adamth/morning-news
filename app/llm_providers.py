"""LLM provider resolution — OpenRouter, OpenAI, Anthropic, or custom OpenAI-compatible APIs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx
from openai import OpenAI

from .config import config
from .credentials import Credentials

logger = logging.getLogger(__name__)

_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_HTTP_TIMEOUT = 120.0


class LlmProviderId(str, Enum):
    openrouter = "openrouter"
    openai = "openai"
    anthropic = "anthropic"
    custom = "custom"


DEFAULT_LLM_MODELS: dict[LlmProviderId, str] = {
    LlmProviderId.openrouter: "openai/gpt-4o-mini",
    LlmProviderId.openai: "gpt-4o-mini",
    LlmProviderId.anthropic: "claude-sonnet-4-20250514",
    LlmProviderId.custom: "gpt-4o-mini",
}

PROVIDER_LABELS: dict[LlmProviderId, str] = {
    LlmProviderId.openrouter: "OpenRouter",
    LlmProviderId.openai: "OpenAI",
    LlmProviderId.anthropic: "Anthropic",
    LlmProviderId.custom: "Custom (OpenAI-compatible URL)",
}


class LlmProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlmProviderConfig:
    provider: LlmProviderId
    model: str
    api_key: str
    base_url: str | None = None


def parse_provider(value: str | None) -> LlmProviderId | None:
    if not value or not value.strip():
        return None
    try:
        return LlmProviderId(value.strip().lower())
    except ValueError:
        return None


def detect_provider_from_credentials(credentials: Credentials) -> LlmProviderId:
    """Pick a provider when settings do not specify one."""

    explicit = parse_provider(config.llm_provider)
    if explicit is not None:
        return explicit

    configured: list[LlmProviderId] = []
    if credentials.openrouter_api_key:
        configured.append(LlmProviderId.openrouter)
    if credentials.openai_api_key:
        configured.append(LlmProviderId.openai)
    if credentials.anthropic_api_key:
        configured.append(LlmProviderId.anthropic)
    if credentials.llm_api_key and credentials.llm_base_url:
        configured.append(LlmProviderId.custom)

    if len(configured) == 1:
        return configured[0]
    if credentials.openrouter_api_key:
        return LlmProviderId.openrouter
    if credentials.openai_api_key:
        return LlmProviderId.openai
    if credentials.anthropic_api_key:
        return LlmProviderId.anthropic
    if credentials.llm_api_key and credentials.llm_base_url:
        return LlmProviderId.custom
    return LlmProviderId.openrouter


def resolve_provider(
    *,
    credentials: Credentials,
    settings_provider: str = "",
    settings_model: str = "",
) -> LlmProviderId:
    explicit = parse_provider(settings_provider)
    if explicit is not None:
        return explicit
    return detect_provider_from_credentials(credentials)


def normalize_model(provider: LlmProviderId, model: str) -> str:
    cleaned = (model or "").strip()
    if not cleaned:
        return DEFAULT_LLM_MODELS[provider]

    if provider is LlmProviderId.openai and "/" in cleaned:
        return DEFAULT_LLM_MODELS[LlmProviderId.openai]
    if provider is LlmProviderId.anthropic:
        if cleaned.startswith("anthropic/"):
            return cleaned.split("/", 1)[1]
        if "/" in cleaned and not cleaned.startswith("claude-"):
            return DEFAULT_LLM_MODELS[LlmProviderId.anthropic]
    if provider is LlmProviderId.openrouter and cleaned.startswith("claude-") and "/" not in cleaned:
        return f"anthropic/{cleaned}"
    return cleaned


def provider_setup_hint(provider: LlmProviderId) -> str:
    return {
        LlmProviderId.openrouter: "Add your OpenRouter API key in Settings → Connections",
        LlmProviderId.openai: "Add your OpenAI API key in Settings → Connections",
        LlmProviderId.anthropic: "Add your Anthropic API key in Settings → Connections",
        LlmProviderId.custom: "Add LLM API key and base URL in Settings → Connections",
    }[provider]


def resolve_api_key(provider: LlmProviderId, credentials: Credentials) -> str | None:
    if provider is LlmProviderId.openrouter:
        return credentials.openrouter_api_key
    if provider is LlmProviderId.openai:
        return credentials.openai_api_key
    if provider is LlmProviderId.anthropic:
        return credentials.anthropic_api_key
    if provider is LlmProviderId.custom:
        return credentials.llm_api_key
    return None


def resolve_provider_config(
    *,
    credentials: Credentials,
    settings_provider: str = "",
    settings_model: str = "",
) -> LlmProviderConfig:
    provider = resolve_provider(
        credentials=credentials,
        settings_provider=settings_provider,
        settings_model=settings_model,
    )
    api_key = resolve_api_key(provider, credentials)
    if not api_key:
        raise LlmProviderError(provider_setup_hint(provider))

    model = normalize_model(provider, settings_model)
    base_url: str | None = None
    if provider is LlmProviderId.openrouter:
        base_url = "https://openrouter.ai/api/v1"
    elif provider is LlmProviderId.openai:
        base_url = "https://api.openai.com/v1"
    elif provider is LlmProviderId.custom:
        base_url = (credentials.llm_base_url or "").rstrip("/") or None
        if not base_url:
            raise LlmProviderError("Add a custom LLM base URL in Settings → Connections")

    return LlmProviderConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)


def openai_client(provider_config: LlmProviderConfig) -> OpenAI:
    if provider_config.provider is LlmProviderId.anthropic:
        raise LlmProviderError("Anthropic uses a separate API client")

    default_headers: dict[str, str] | None = None
    if provider_config.provider is LlmProviderId.openrouter:
        default_headers = {
            "HTTP-Referer": config.base_url or "http://localhost",
            "X-Title": "Morning News Podcast Generator",
        }

    return OpenAI(
        base_url=provider_config.base_url,
        api_key=provider_config.api_key,
        default_headers=default_headers,
    )


def chat_completion(
    *,
    provider_config: LlmProviderConfig,
    system: str,
    user: str,
    temperature: float,
    json_mode: bool = False,
) -> str:
    if provider_config.provider is LlmProviderId.anthropic:
        return _anthropic_completion(
            api_key=provider_config.api_key,
            model=provider_config.model,
            system=system,
            user=user,
            temperature=temperature,
        )

    client = openai_client(provider_config)
    kwargs: dict[str, Any] = {
        "model": provider_config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()


def _anthropic_completion(
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float,
) -> str:
    try:
        response = httpx.post(
            _ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 8192,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "temperature": temperature,
            },
            timeout=_HTTP_TIMEOUT,
        )
        if response.status_code == 401:
            raise LlmProviderError("Anthropic API key was rejected")
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as error:
        raise LlmProviderError(f"Could not reach Anthropic: {error}") from error
    except ValueError as error:
        raise LlmProviderError(f"Unexpected Anthropic response: {error}") from error

    blocks = payload.get("content") or []
    text_parts = [block.get("text", "") for block in blocks if block.get("type") == "text"]
    content = "".join(text_parts).strip()
    if not content:
        raise LlmProviderError("Anthropic returned an empty response")
    return content


def available_providers(credentials: Credentials) -> list[LlmProviderId]:
    """Providers that have credentials configured."""

    providers: list[LlmProviderId] = []
    if credentials.openrouter_api_key:
        providers.append(LlmProviderId.openrouter)
    if credentials.openai_api_key:
        providers.append(LlmProviderId.openai)
    if credentials.anthropic_api_key:
        providers.append(LlmProviderId.anthropic)
    if credentials.llm_api_key and credentials.llm_base_url:
        providers.append(LlmProviderId.custom)
    return providers
