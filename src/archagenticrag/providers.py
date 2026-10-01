"""OpenAI-compatible model provider presets (shared by the RAG graphs and the evaluator).

Every provider we use exposes an OpenAI-compatible endpoint, Ollama included
(``http://localhost:11434/v1``). So one client type covers all of them:
``langchain_openai.ChatOpenAI`` for the graphs, and ``openai.AsyncOpenAI`` for Ragas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str | None  # None = SDK default (api.openai.com)
    api_key_env: str | None  # None = no key needed (local server)
    base_url_env: str | None = None  # optional override, e.g. a remote Ollama host


# Base URLs checked 2026-10-01: OpenRouter and NVIDIA /models answer 200 without a key,
# xAI and Groq answer 401 (endpoint exists), and Gemini is per
# https://ai.google.dev/gemini-api/docs/openai (it needs a key even for /models).
# Ollama's OpenAI-compatible API is documented at https://docs.ollama.com/api/openai-compatibility.
PROVIDERS: dict[str, ProviderPreset] = {
    "ollama": ProviderPreset("http://localhost:11434/v1", None, "OLLAMA_BASE_URL"),
    "gemini": ProviderPreset("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "openrouter": ProviderPreset("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "nvidia": ProviderPreset("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "xai": ProviderPreset("https://api.x.ai/v1", "XAI_API_KEY"),
    "groq": ProviderPreset("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openai": ProviderPreset(None, "OPENAI_API_KEY"),
}


class ProviderError(RuntimeError):
    pass


def resolve(provider: str) -> tuple[str | None, str]:
    """Return (base_url, api_key) for a provider, failing loudly if a required key is missing."""
    preset = PROVIDERS.get(provider)
    if preset is None:
        raise ProviderError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    base_url = (os.environ.get(preset.base_url_env) if preset.base_url_env else None) or preset.base_url
    if preset.api_key_env is None:
        return base_url, "not-needed"  # the OpenAI SDK insists on a non-empty key
    api_key = os.environ.get(preset.api_key_env)
    if not api_key:
        raise ProviderError(f"provider {provider!r} needs environment variable {preset.api_key_env}")
    return base_url, api_key


def async_client(provider: str):
    from openai import AsyncOpenAI

    base_url, api_key = resolve(provider)
    return AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=6)


def chat_model(provider: str, model: str, temperature: float | None = None, max_tokens: int | None = None):
    """A LangChain chat model for any preset provider."""
    from langchain_openai import ChatOpenAI

    base_url, api_key = resolve(provider)
    kwargs = {} if temperature is None else {"temperature": temperature}
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    # max_retries: the OpenAI SDK retries 429/5xx with exponential backoff (free tiers rate-limit hard).
    return ChatOpenAI(model=model, base_url=base_url, api_key=api_key, max_retries=6, **kwargs)


async def assert_models_available(provider: str, models: list[str]) -> None:
    """Preflight: fail before a long run if the provider does not list a configured model."""
    client = async_client(provider)
    available = {m.id async for m in client.models.list()}
    # Gemini lists ids as "models/<name>"; accept either spelling.
    available |= {m.removeprefix("models/") for m in available}
    missing = [m for m in models if m not in available]
    if missing:
        raise ProviderError(f"provider {provider!r} does not list model(s) {missing}")
