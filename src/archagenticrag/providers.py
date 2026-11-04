"""OpenAI-compatible model provider presets (shared by the RAG graphs and the evaluator).

Every provider we use exposes an OpenAI-compatible endpoint, Ollama included
(``http://localhost:11434/v1``). So one client type covers all of them:
``langchain_openai.ChatOpenAI`` for the graphs, and ``openai.AsyncOpenAI`` for Ragas.

Optional multi-provider fallback (``ProviderStrategy``, mode ``fallback``) is opt-in per config
and implemented in :mod:`archagenticrag.provider_fallback`. Without a strategy, or with mode
``single``, clients are built exactly as before.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str | None  # None = SDK default (api.openai.com)
    api_key_env: str | None  # None = no key needed (local server)
    base_url_env: str | None = None  # optional override, e.g. a remote Ollama host
    url_vars: tuple[str, ...] = field(default=())  # env vars substituted into base_url, e.g. an account id


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
    # Added 2026-10-28 for multi-provider fallback; OpenAI compatibility per the providers' docs:
    # https://inference-docs.cerebras.ai/resources/openai, https://docs.sambanova.ai/docs/en/features/openai-compatibility.md,
    # https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/ . Without a key:
    # Cerebras /models answers 403, SambaNova 200, Cloudflare /ai/v1 exists (405 on GET /models).
    "cerebras": ProviderPreset("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "sambanova": ProviderPreset("https://api.sambanova.ai/v1", "SAMBANOVA_API_KEY"),
    "cloudflare": ProviderPreset(
        "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        "CLOUDFLARE_API_TOKEN",
        url_vars=("CLOUDFLARE_ACCOUNT_ID",),
    ),
}


class ProviderError(RuntimeError):
    pass


def missing_settings(provider: str) -> list[str]:
    """Names (never values) of the environment variables a provider still needs."""
    preset = PROVIDERS.get(provider)
    if preset is None:
        raise ProviderError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    names = [*preset.url_vars, *([preset.api_key_env] if preset.api_key_env else [])]
    return [name for name in names if not os.environ.get(name)]


def resolve(provider: str) -> tuple[str | None, str]:
    """Return (base_url, api_key) for a provider, failing loudly if a required key is missing."""
    preset = PROVIDERS.get(provider)
    if preset is None:
        raise ProviderError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    base_url = (os.environ.get(preset.base_url_env) if preset.base_url_env else None) or preset.base_url
    if preset.url_vars:
        missing = [name for name in preset.url_vars if not os.environ.get(name)]
        if missing:
            raise ProviderError(f"provider {provider!r} needs environment variable(s) {missing}")
        base_url = base_url.format(**{name: os.environ[name] for name in preset.url_vars})
    if preset.api_key_env is None:
        return base_url, "not-needed"  # the OpenAI SDK insists on a non-empty key
    api_key = os.environ.get(preset.api_key_env)
    if not api_key:
        raise ProviderError(f"provider {provider!r} needs environment variable {preset.api_key_env}")
    return base_url, api_key


class FallbackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _known(self) -> FallbackTarget:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}; known: {sorted(PROVIDERS)}")
        return self


class ProviderStrategy(BaseModel):
    """How one model role (generator or judge) reaches its provider(s).

    ``single``: the configured provider only (the default, and what every run before this
    feature used). ``fallback``: the configured provider first, then ``fallbacks`` in the listed
    order. Fallback providers whose environment variables are missing are skipped (and recorded);
    the primary provider is required.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "fallback"] = "single"
    fallbacks: list[FallbackTarget] = Field(default_factory=list)
    max_retries_per_provider: int = Field(default=1, ge=0, le=3)
    retry_backoff_s: float = Field(default=2.0, ge=0, le=30)
    max_retry_after_s: float = Field(default=10.0, ge=0, le=60)
    timeout_s: float = Field(default=60.0, gt=0, le=600)

    @model_validator(mode="after")
    def _mode_matches_fallbacks(self) -> ProviderStrategy:
        if self.mode == "fallback" and not self.fallbacks:
            raise ValueError("provider_strategy mode 'fallback' needs at least one entry in fallbacks")
        if self.mode == "single" and self.fallbacks:
            raise ValueError("provider_strategy mode 'single' takes no fallbacks")
        return self


def _fallback(strategy: Any) -> ProviderStrategy | None:
    if strategy is None:
        return None
    strategy = strategy if isinstance(strategy, ProviderStrategy) else ProviderStrategy.model_validate(strategy)
    return strategy if strategy.mode == "fallback" else None


def plan_routes(provider: str, model: str, strategy: ProviderStrategy) -> dict[str, Any]:
    """Configured order, participating routes and skipped providers (names of missing variables only)."""
    configured = [(provider, model), *((t.provider, t.model) for t in strategy.fallbacks)]
    if len(set(configured)) != len(configured):
        raise ProviderError(f"provider_strategy lists the same provider/model twice: {configured}")
    missing = missing_settings(provider)
    if missing:
        raise ProviderError(f"primary provider {provider!r} needs environment variable(s) {missing}")
    participating, skipped = [], []
    for name, target_model in configured:
        missing = missing_settings(name)
        if missing:
            skipped.append({"provider": name, "model": target_model, "missing_env": missing})
        else:
            participating.append((name, target_model))
    return {
        "mode": strategy.mode,
        "configured_order": [{"provider": p, "model": m} for p, m in configured],
        "participating": [{"provider": p, "model": m} for p, m in participating],
        "skipped": skipped,
        "retry_policy": {
            "max_retries_per_provider": strategy.max_retries_per_provider,
            "retry_backoff_s": strategy.retry_backoff_s,
            "max_retry_after_s": strategy.max_retry_after_s,
            "timeout_s": strategy.timeout_s,
        },
    }


def fallback_transport(provider: str, model: str, strategy: ProviderStrategy, role: str, inner: Any = None):
    from archagenticrag.provider_fallback import FallbackTransport, RetryPolicy, Route

    routes = []
    for item in plan_routes(provider, model, strategy)["participating"]:
        base_url, api_key = resolve(item["provider"])
        routes.append(Route(item["provider"], item["model"], base_url or "https://api.openai.com/v1", api_key))
    policy = RetryPolicy(strategy.max_retries_per_provider, strategy.retry_backoff_s, strategy.max_retry_after_s)
    return FallbackTransport(routes, role=role, policy=policy, inner=inner)


def async_client(provider: str, *, model: str | None = None, strategy: Any = None, role: str = "judge", inner_transport: Any = None):
    """OpenAI async client. With a fallback strategy (and the primary ``model``) requests go through
    the fallback transport; the SDK's own retries are off because the transport owns retrying."""
    from openai import AsyncOpenAI

    fallback = _fallback(strategy)
    if fallback is None:
        base_url, api_key = resolve(provider)
        return AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=6)
    import httpx

    from archagenticrag.provider_fallback import PLACEHOLDER_BASE_URL

    if model is None:
        raise ProviderError("a fallback client needs the primary model")
    transport = fallback_transport(provider, model, fallback, role, inner_transport)
    return AsyncOpenAI(
        base_url=PLACEHOLDER_BASE_URL,
        api_key="routed-by-provider-fallback",  # the transport sets each provider's own key
        max_retries=0,
        timeout=fallback.timeout_s,
        http_client=httpx.AsyncClient(transport=transport, timeout=fallback.timeout_s),
    )


def chat_model(
    provider: str,
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    *,
    strategy: Any = None,
    inner_transport: Any = None,
):
    """A LangChain chat model for any preset provider (optionally behind the fallback transport)."""
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {} if temperature is None else {"temperature": temperature}
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    fallback = _fallback(strategy)
    if fallback is None:
        base_url, api_key = resolve(provider)
        # max_retries: the OpenAI SDK retries 429/5xx with exponential backoff (free tiers rate-limit hard).
        return ChatOpenAI(model=model, base_url=base_url, api_key=api_key, max_retries=6, **kwargs)
    import httpx

    from archagenticrag.provider_fallback import PLACEHOLDER_BASE_URL

    transport = fallback_transport(provider, model, fallback, "generator", inner_transport)
    return ChatOpenAI(
        model=model,
        base_url=PLACEHOLDER_BASE_URL,
        api_key="routed-by-provider-fallback",
        max_retries=0,
        timeout=fallback.timeout_s,
        http_client=httpx.Client(transport=transport, timeout=fallback.timeout_s),
        http_async_client=httpx.AsyncClient(transport=transport, timeout=fallback.timeout_s),
        **kwargs,
    )


async def assert_models_available(provider: str, models: list[str]) -> None:
    """Preflight: fail before a long run if the provider does not list a configured model."""
    client = async_client(provider)
    available = {m.id async for m in client.models.list()}
    # Gemini lists ids as "models/<name>"; accept either spelling.
    available |= {m.removeprefix("models/") for m in available}
    missing = [m for m in models if m not in available]
    if missing:
        raise ProviderError(f"provider {provider!r} does not list model(s) {missing}")
