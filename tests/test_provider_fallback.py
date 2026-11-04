"""Multi-provider fallback (docs/MULTI-PROVIDER-FALLBACK.md). Offline: every provider is an
httpx.MockTransport, so no request leaves the machine and no quota is used."""

from __future__ import annotations

import json
from collections import defaultdict

import httpx
import openai
import pytest

from archagenticrag.provider_fallback import (
    EXHAUSTED,
    FailureType,
    FallbackTransport,
    RetryPolicy,
    Route,
    classify_exception,
    classify_status,
    collect_provider_calls,
    provider_health,
    render_health,
    retry_after_seconds,
)
from archagenticrag.providers import (
    ProviderError,
    ProviderStrategy,
    async_client,
    chat_model,
    plan_routes,
)

KEYS = {
    "GEMINI_API_KEY": "gm-secret-key-0001",
    "CEREBRAS_API_KEY": "cb-secret-key-0002",
    "GROQ_API_KEY": "gq-secret-key-0003",
}
HOSTS = {"generativelanguage.googleapis.com": "gemini", "api.cerebras.ai": "cerebras", "api.groq.com": "groq"}
STRATEGY = {
    "mode": "fallback",
    "fallbacks": [{"provider": "cerebras", "model": "llama-3.3-70b"}, {"provider": "groq", "model": "openai/gpt-oss-120b"}],
    "max_retries_per_provider": 1,
    "retry_backoff_s": 0,  # no real waiting in tests; waits are tested with an injected sleep below
    "max_retry_after_s": 5,
}


@pytest.fixture
def env(monkeypatch):
    for name in ("SAMBANOVA_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)


def completion(model: str, text: str = "ok") -> dict:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }


class Providers:
    """Scripted providers: host -> queue of (status, body | exception, headers); records every request."""

    def __init__(self, script: dict[str, list]):
        self.script = {k: list(v) for k, v in script.items()}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        provider = HOSTS[request.url.host]
        queue = self.script.get(provider) or [(200, None, {})]
        status, body, headers = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(body, Exception):
            raise body
        if status == 200 and body is None:
            body = completion(json.loads(request.content)["model"], f"from {provider}")
        content = body if isinstance(body, bytes) else json.dumps(body if body is not None else {"error": {"message": "err"}}).encode()
        return httpx.Response(status, headers={"content-type": "application/json", **headers}, content=content)

    def providers_called(self) -> list[str]:
        return [HOSTS[r.url.host] for r in self.requests]


def err(message: str) -> dict:
    return {"error": {"message": message}}


def _llm(script, strategy=STRATEGY):
    providers = Providers(script)
    llm = chat_model("gemini", "gemini-2.5-flash", 0, strategy=strategy, inner_transport=httpx.MockTransport(providers))
    return llm, providers


# ---- classification ----


@pytest.mark.parametrize(
    ("status", "text", "expected"),
    [
        (429, "Too many requests", FailureType.RATE_LIMIT),
        (413, "Request too large ... on tokens per minute (TPM): Limit 8000", FailureType.RATE_LIMIT),
        (500, "", FailureType.TRANSIENT_SERVER_ERROR),
        (502, "", FailureType.TRANSIENT_SERVER_ERROR),
        (503, "overloaded", FailureType.PROVIDER_UNAVAILABLE),
        (504, "", FailureType.TIMEOUT),
        (408, "", FailureType.TIMEOUT),
        (401, "invalid api key", FailureType.AUTHENTICATION_ERROR),
        (403, "forbidden", FailureType.AUTHENTICATION_ERROR),
        (404, "model not found", FailureType.MODEL_NOT_FOUND),
        (400, "This model's maximum context length is 8192 tokens", FailureType.CONTEXT_LENGTH),
        (400, "Invalid value for temperature", FailureType.INVALID_REQUEST),
        (422, "unprocessable", FailureType.INVALID_REQUEST),
        (418, "", FailureType.UNKNOWN),
    ],
)
def test_classify_status(status, text, expected):
    assert classify_status(status, text) is expected


def test_classify_exceptions_and_retry_after():
    assert classify_exception(httpx.ReadTimeout("slow")) is FailureType.TIMEOUT
    assert classify_exception(httpx.ConnectError("refused")) is FailureType.PROVIDER_UNAVAILABLE
    assert classify_exception(ValueError("x")) is FailureType.UNKNOWN
    assert retry_after_seconds(httpx.Headers({"retry-after": "3"})) == 3.0
    assert retry_after_seconds(httpx.Headers({"retry-after-ms": "1500"})) == 1.5
    assert retry_after_seconds(httpx.Headers({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})) is None
    assert retry_after_seconds(httpx.Headers({})) is None


# ---- provider selection ----


def test_only_configured_providers_participate_in_the_configured_order(env):
    strategy = ProviderStrategy.model_validate(
        {**STRATEGY, "fallbacks": [*STRATEGY["fallbacks"][:1], {"provider": "sambanova", "model": "m"}, STRATEGY["fallbacks"][1]]}
    )
    plan = plan_routes("gemini", "gemini-2.5-flash", strategy)
    assert [r["provider"] for r in plan["configured_order"]] == ["gemini", "cerebras", "sambanova", "groq"]
    assert [r["provider"] for r in plan["participating"]] == ["gemini", "cerebras", "groq"]
    assert plan["skipped"] == [{"provider": "sambanova", "model": "m", "missing_env": ["SAMBANOVA_API_KEY"]}]


def test_priority_order_comes_from_the_config(env):
    reordered = ProviderStrategy.model_validate({**STRATEGY, "fallbacks": list(reversed(STRATEGY["fallbacks"]))})
    assert [r["provider"] for r in plan_routes("gemini", "g", reordered)["participating"]] == ["gemini", "groq", "cerebras"]


def test_explicit_primary_without_credentials_is_a_configuration_error(env, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        plan_routes("gemini", "g", ProviderStrategy.model_validate(STRATEGY))
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        chat_model("gemini", "g")  # single mode: as before


def test_cloudflare_needs_token_and_account_id(env, monkeypatch):
    strategy = ProviderStrategy.model_validate({"mode": "fallback", "fallbacks": [{"provider": "cloudflare", "model": "@cf/meta/llama-3.1-8b-instruct"}]})
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token-value")
    assert plan_routes("gemini", "g", strategy)["skipped"][0]["missing_env"] == ["CLOUDFLARE_ACCOUNT_ID"]
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct123")
    from archagenticrag.providers import resolve

    assert resolve("cloudflare")[0] == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/v1"


def test_strategy_validation():
    with pytest.raises(ValueError):
        ProviderStrategy.model_validate({"mode": "fallback"})  # no fallbacks
    with pytest.raises(ValueError):
        ProviderStrategy.model_validate({"mode": "single", "fallbacks": STRATEGY["fallbacks"]})
    with pytest.raises(ValueError):
        ProviderStrategy.model_validate({**STRATEGY, "max_retries_per_provider": 10})  # bounded
    with pytest.raises(ValueError):
        ProviderStrategy.model_validate({**STRATEGY, "fallbacks": [{"provider": "dsh", "model": "x"}]})  # unaudited provider
    with pytest.raises(ProviderError, match="twice"):
        plan_routes("groq", "openai/gpt-oss-120b", ProviderStrategy.model_validate(STRATEGY))


# ---- fallback through the real LangChain / OpenAI clients ----


def test_429_falls_back_and_records_identity(env):
    llm, providers = _llm({"gemini": [(429, err("Resource exhausted"), {})]})
    with collect_provider_calls() as calls:
        assert llm.invoke("hi").content == "from cerebras"
    assert providers.providers_called() == ["gemini", "gemini", "cerebras"]  # 1 retry, then fallback
    (call,) = calls
    assert call | {"attempts": None, "timestamp": None} == {
        "role": "generator",
        "primary_provider": "gemini",
        "primary_model": "gemini-2.5-flash",
        "actual_provider": "cerebras",
        "actual_model": "llama-3.3-70b",
        "fallback_used": True,
        "fallback_reason": "RATE_LIMIT",
        "outcome": "success",
        "attempts": None,
        "usage": {"input_tokens": 11, "output_tokens": 3},
        "timestamp": None,
    }
    assert [a["status_code"] for a in call["attempts"]] == [429, 429, 200]
    # each provider got its own model name, URL and key; the body is otherwise unchanged
    sent = [json.loads(r.content) for r in providers.requests]
    assert [b["model"] for b in sent] == ["gemini-2.5-flash", "gemini-2.5-flash", "llama-3.3-70b"]
    assert all(b["temperature"] == 0 for b in sent)
    assert str(providers.requests[-1].url) == "https://api.cerebras.ai/v1/chat/completions"
    assert providers.requests[-1].headers["authorization"] == f"Bearer {KEYS['CEREBRAS_API_KEY']}"


def test_two_rate_limits_then_third_provider(env):
    llm, providers = _llm({"gemini": [(429, err("x"), {})], "cerebras": [(429, err("y"), {})]})
    with collect_provider_calls() as calls:
        assert llm.invoke("hi").content == "from groq"
    assert providers.providers_called() == ["gemini", "gemini", "cerebras", "cerebras", "groq"]
    assert calls[0]["actual_provider"] == "groq" and calls[0]["fallback_reason"] == "RATE_LIMIT"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ((503, err("overloaded"), {}), "PROVIDER_UNAVAILABLE"),
        ((500, err("boom"), {}), "TRANSIENT_SERVER_ERROR"),
        ((504, err("gateway timeout"), {}), "TIMEOUT"),
        ((0, httpx.ReadTimeout("read timed out"), {}), "TIMEOUT"),
        ((0, httpx.ConnectError("connection refused"), {}), "PROVIDER_UNAVAILABLE"),
    ],
)
def test_transient_failures_fall_back(env, failure, reason):
    llm, providers = _llm({"gemini": [failure]})
    with collect_provider_calls() as calls:
        assert llm.invoke("hi").content == "from cerebras"
    assert calls[0]["fallback_reason"] == reason and calls[0]["fallback_used"] is True


@pytest.mark.parametrize(
    ("failure", "exc_type", "reason"),
    [
        ((401, err("Invalid API key"), {}), openai.AuthenticationError, "AUTHENTICATION_ERROR"),
        ((400, err("Invalid value for 'temperature'"), {}), openai.BadRequestError, "INVALID_REQUEST"),
        ((400, err("maximum context length is 8192 tokens"), {}), openai.BadRequestError, "CONTEXT_LENGTH"),
        ((404, err("The model `x` does not exist"), {}), openai.NotFoundError, "MODEL_NOT_FOUND"),
    ],
)
def test_configuration_errors_surface_without_fallback(env, failure, exc_type, reason):
    llm, providers = _llm({"gemini": [failure]})
    with collect_provider_calls() as calls, pytest.raises(exc_type):
        llm.invoke("hi")
    assert providers.providers_called() == ["gemini"]  # no retry, no other provider
    assert calls[0]["outcome"] == "error" and calls[0]["attempts"][0]["error_type"] == reason
    assert calls[0]["fallback_used"] is False


# ---- retry policy ----


def _transport(script, policy=RetryPolicy(1, 0.5, 5), sleeps=None):
    providers = Providers(script)
    routes = [Route("gemini", "g", "https://generativelanguage.googleapis.com/v1beta/openai", KEYS["GEMINI_API_KEY"]),
              Route("cerebras", "c", "https://api.cerebras.ai/v1", KEYS["CEREBRAS_API_KEY"])]  # fmt: skip
    sleeps = sleeps if sleeps is not None else []
    transport = FallbackTransport(routes, role="judge", policy=policy, inner=httpx.MockTransport(providers), sleep=sleeps.append)
    client = openai.OpenAI(base_url="http://provider-fallback.invalid/v1", api_key="x", max_retries=0, http_client=httpx.Client(transport=transport))
    return client, providers, sleeps


def _ask(client):
    return client.chat.completions.create(model="g", messages=[{"role": "user", "content": "hi"}]).choices[0].message.content


def test_retry_then_success_on_the_same_provider(env):
    client, providers, sleeps = _transport({"gemini": [(429, err("busy"), {}), (200, None, {})]})
    with collect_provider_calls() as calls:
        assert _ask(client) == "from gemini"
    assert providers.providers_called() == ["gemini", "gemini"] and sleeps == [0.5]
    assert calls[0]["fallback_used"] is False and calls[0]["actual_provider"] == "gemini"


def test_retry_after_is_honoured_when_short_and_skipped_when_long(env):
    client, providers, sleeps = _transport({"gemini": [(429, err("busy"), {"retry-after": "2"})]})
    _ask(client)
    assert sleeps == [2.0]
    client, providers, sleeps = _transport({"gemini": [(429, err("busy"), {"retry-after": "30"})]})
    with collect_provider_calls() as calls:
        _ask(client)
    assert sleeps == [] and providers.providers_called() == ["gemini", "cerebras"]  # 30 s > max_retry_after_s: move on
    assert calls[0]["attempts"][0]["retry_after_s"] == 30.0


def test_daily_quota_is_not_retried_on_the_same_provider(env):
    client, providers, sleeps = _transport({"gemini": [(429, err("Limit 200000 tokens per day (TPD)"), {})]})
    with collect_provider_calls() as calls:
        _ask(client)
    assert providers.providers_called() == ["gemini", "cerebras"] and sleeps == []
    assert calls[0]["attempts"][0]["daily_quota"] is True


def test_retry_exhaustion_across_all_providers_is_a_resumable_rate_limit(env):
    client, providers, sleeps = _transport({"gemini": [(429, err("a"), {})], "cerebras": [(503, err("b"), {})]}, policy=RetryPolicy(2, 0.1, 5))
    with collect_provider_calls() as calls, pytest.raises(openai.RateLimitError, match=EXHAUSTED):
        _ask(client)
    assert providers.providers_called() == ["gemini"] * 3 + ["cerebras"] * 3  # bounded: 1 + 2 retries each
    assert sleeps == [0.1] * 4
    assert calls[0]["outcome"] == EXHAUSTED and calls[0]["actual_provider"] is None


async def test_async_client_falls_back_for_the_judge(env):
    providers = Providers({"gemini": [(429, err("x"), {})]})
    client = async_client("gemini", model="gemini-2.5-flash", strategy=STRATEGY, role="judge", inner_transport=httpx.MockTransport(providers))
    with collect_provider_calls() as calls:
        out = await client.chat.completions.create(model="gemini-2.5-flash", messages=[{"role": "user", "content": "hi"}])
    assert out.choices[0].message.content == "from cerebras"
    assert calls[0]["role"] == "judge" and calls[0]["actual_model"] == "llama-3.3-70b"


async def test_langchain_async_path_records_per_task(env):
    import asyncio

    llm, _ = _llm({"gemini": [(429, err("x"), {})]})

    async def one():
        with collect_provider_calls() as calls:
            await llm.ainvoke("hi")
        return calls

    first, second = await asyncio.gather(one(), one())
    assert len(first) == len(second) == 1  # each concurrent item sees only its own requests


# ---- metadata, health, security ----


def test_provider_health_summary(env):
    llm, _ = _llm({"gemini": [(429, err("x"), {}), (429, err("x"), {}), (200, None, {})]}, strategy={**STRATEGY, "max_retries_per_provider": 1})
    records = []
    for _ in range(2):
        with collect_provider_calls() as calls:
            llm.invoke("hi")
        records.append({"provider_calls": calls})
    health = provider_health(records)["generator"]
    assert health["gemini"]["requests"] == 3 and health["gemini"]["rate_limits"] == 2 and health["gemini"]["fallbacks"] == 1
    assert health["gemini"]["successful_requests"] == 1
    assert health["cerebras"]["served_as_fallback"] == 1 and health["cerebras"]["input_tokens"] == 11
    assert "Provider Health" in render_health(provider_health(records))


def test_api_keys_never_appear_in_records_errors_or_reprs(env):
    echoed = err(f"bad key {KEYS['GEMINI_API_KEY']} rejected")  # a provider echoing the key back
    llm, _ = _llm({"gemini": [(429, echoed, {})], "cerebras": [(429, err("x"), {})], "groq": [(429, err("y"), {})]})
    with collect_provider_calls() as calls, pytest.raises(openai.RateLimitError) as raised:
        llm.invoke("hi")
    dumped = json.dumps(calls) + str(raised.value) + repr(llm) + repr(plan_routes("gemini", "g", ProviderStrategy.model_validate(STRATEGY)))
    for secret in KEYS.values():
        assert secret not in dumped
    assert "[REDACTED]" in json.dumps(calls)


def test_single_mode_and_no_strategy_build_the_original_client(env):
    for strategy in (None, {"mode": "single"}):
        llm = chat_model("groq", "openai/gpt-oss-120b", 0, strategy=strategy)
        assert llm.openai_api_base == "https://api.groq.com/openai/v1" and llm.max_retries == 6
    client = async_client("groq")
    assert str(client.base_url).startswith("https://api.groq.com/openai/v1") and client.max_retries == 6

