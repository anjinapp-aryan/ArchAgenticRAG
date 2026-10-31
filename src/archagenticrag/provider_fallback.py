"""Opt-in multi-provider fallback for OpenAI-compatible chat calls (docs/MULTI-PROVIDER-FALLBACK.md).

Both model clients the project uses are the OpenAI SDK on top of httpx: LangChain's
``ChatOpenAI`` (RAG graphs) and ``openai.AsyncOpenAI`` (the Ragas judge). Fallback is
therefore done once, as an httpx transport, and works for both without either knowing:

  * the SDK sends ``POST <placeholder>/chat/completions`` with the primary model;
  * the transport sends it to route 1 (base URL, key, model substituted in the body), and on a
    fallback-eligible failure retries that route a bounded number of times, then moves to the
    next configured route;
  * any other failure (auth, bad request, context length, unknown model) is returned to the SDK
    untouched, so it raises its usual exception and nothing is hidden;
  * if every route fails, a synthetic 429 whose message starts with ``PROVIDER_EXHAUSTED`` is
    returned, so the SDK raises ``RateLimitError`` and the evaluator records a resumable error.

Every request is recorded (attempts, actual provider/model, fallback reason, tokens) in the
list opened by ``collect_provider_calls()``; keys are never recorded and are redacted from any
stored provider message. Request bodies other than the ``model`` field are sent unchanged, so
temperature and token limits are identical on every route.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable, Iterator

import httpx

PLACEHOLDER_BASE_URL = "http://provider-fallback.invalid/v1"  # never contacted; the transport reroutes
EXHAUSTED = "PROVIDER_EXHAUSTED"
# Provider messages for daily (not per-minute) quotas: retrying the same provider cannot help.
DAILY_QUOTA_MARKERS = ("tokens per day", "requests per day", "(TPD)", "(RPD)", "PerDay")
_RATE_LIMIT_TEXT = ("rate limit", "tokens per minute", "requests per minute", "(TPM)", "(RPM)", "quota")
_CONTEXT_TEXT = ("context length", "context_length", "maximum context", "context window", "too many tokens", "prompt is too long")


class FailureType(StrEnum):
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT_SERVER_ERROR = "TRANSIENT_SERVER_ERROR"
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    CONTEXT_LENGTH = "CONTEXT_LENGTH"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    UNKNOWN = "UNKNOWN"


FALLBACK_ELIGIBLE = frozenset(
    {FailureType.RATE_LIMIT, FailureType.TRANSIENT_SERVER_ERROR, FailureType.TIMEOUT, FailureType.PROVIDER_UNAVAILABLE}
)


def classify_status(status: int, text: str = "") -> FailureType:
    """Map an HTTP error response to a failure type. ``text`` is the response body."""
    lower = text.lower()
    if status == 429:
        return FailureType.RATE_LIMIT
    if status in (401, 403):
        return FailureType.AUTHENTICATION_ERROR
    if status == 404:
        return FailureType.MODEL_NOT_FOUND
    if status in (400, 413, 422):
        if any(m.lower() in lower for m in _CONTEXT_TEXT):
            return FailureType.CONTEXT_LENGTH
        # Groq answers 413 "Request too large ... tokens per minute (TPM)" when one request exceeds
        # the per-minute budget: a capacity limit, not a malformed request.
        if status == 413 and any(m.lower() in lower for m in _RATE_LIMIT_TEXT):
            return FailureType.RATE_LIMIT
        return FailureType.INVALID_REQUEST
    if status in (408, 504):
        return FailureType.TIMEOUT
    if status == 503:
        return FailureType.PROVIDER_UNAVAILABLE
    if status >= 500:
        return FailureType.TRANSIENT_SERVER_ERROR
    return FailureType.UNKNOWN


def classify_exception(exc: BaseException) -> FailureType:
    if isinstance(exc, httpx.TimeoutException):
        return FailureType.TIMEOUT
    if isinstance(exc, httpx.TransportError):  # connection refused, DNS, reset
        return FailureType.PROVIDER_UNAVAILABLE
    return FailureType.UNKNOWN


def is_daily_quota(text: str) -> bool:
    return any(marker in text for marker in DAILY_QUOTA_MARKERS)


def retry_after_seconds(headers: httpx.Headers) -> float | None:
    """Seconds from ``Retry-After`` (delta form) or ``retry-after-ms``; None when absent or a date."""
    if headers.get("retry-after-ms"):
        with contextlib.suppress(ValueError):
            return float(headers["retry-after-ms"]) / 1000
    with contextlib.suppress(ValueError, TypeError):
        return float(headers.get("retry-after"))
    return None


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    base_url: str
    api_key: str  # never recorded

    def __repr__(self) -> str:  # keep the key out of reprs and tracebacks
        return f"Route(provider={self.provider!r}, model={self.model!r})"


@dataclass(frozen=True)
class RetryPolicy:
    max_retries_per_provider: int = 1
    retry_backoff_s: float = 2.0  # fixed wait between retries on the same provider (no exponential growth)
    max_retry_after_s: float = 10.0  # a longer Retry-After moves on to the next provider instead of waiting


_calls: ContextVar[list[dict[str, Any]] | None] = ContextVar("provider_calls", default=None)


@contextlib.contextmanager
def collect_provider_calls() -> Iterator[list[dict[str, Any]]]:
    """Collect the provider call records made inside the block (per item; works across asyncio tasks
    and LangChain's executor threads, which copy the context)."""
    calls: list[dict[str, Any]] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FallbackTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """httpx transport that sends each chat request along an ordered list of routes."""

    def __init__(
        self,
        routes: list[Route],
        *,
        role: str,
        policy: RetryPolicy = RetryPolicy(),
        inner: Any = None,
        sleep: Callable[[float], Any] | None = None,
        async_sleep: Callable[[float], Any] | None = None,
    ) -> None:
        if not routes:
            raise ValueError("FallbackTransport needs at least one route")
        self.routes = routes
        self.role = role
        self.policy = policy
        self._sync_inner = inner if inner is not None else httpx.HTTPTransport()
        self._async_inner = inner if inner is not None else httpx.AsyncHTTPTransport()
        self._sleep = sleep or time.sleep
        self._async_sleep = async_sleep or asyncio.sleep
        self._secrets = [r.api_key for r in routes if r.api_key and len(r.api_key) >= 6]

    # request plumbing

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    @staticmethod
    def _suffix(request: httpx.Request) -> str:
        base = httpx.URL(PLACEHOLDER_BASE_URL).path.rstrip("/")
        path = request.url.path
        return path[len(base) :] if path.startswith(base) else path

    def _build(self, request: httpx.Request, body: bytes, route: Route) -> httpx.Request:
        suffix = self._suffix(request)
        content = body
        if suffix.endswith("/chat/completions") and body:
            payload = json.loads(body)
            payload["model"] = route.model
            content = json.dumps(payload).encode()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization", "content-length")}
        headers["Authorization"] = f"Bearer {route.api_key}"
        url = httpx.URL(route.base_url.rstrip("/") + suffix, params=request.url.params)
        return httpx.Request(request.method, url, headers=headers, content=content, extensions=request.extensions)

    @staticmethod
    def _rebuild(original: httpx.Request, response: httpx.Response, body: bytes) -> httpx.Response:
        headers = [(k, v) for k, v in response.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        return httpx.Response(response.status_code, headers=headers, content=body, request=original)

    @staticmethod
    def _usage(body: bytes) -> dict[str, int] | None:
        with contextlib.suppress(ValueError, AttributeError, TypeError):
            usage = json.loads(body).get("usage")
            if usage:
                return {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}
        return None

    def _exhausted(self, original: httpx.Request, record: dict[str, Any]) -> httpx.Response:
        tried = ", ".join(f"{a['provider']}:{a['error_type']}" for a in record["attempts"])
        message = f"{EXHAUSTED}: every {self.role} provider failed ({tried})"
        body = json.dumps({"error": {"message": message, "type": "provider_exhausted", "code": EXHAUSTED}}).encode()
        return httpx.Response(429, headers={"content-type": "application/json"}, content=body, request=original)

    # the fallback loop, written once as a generator of "send" / "sleep" steps

    def _plan(self, request: httpx.Request, body: bytes):
        """Yields ("send", request) or ("sleep", seconds); receives (response, body) or an exception."""
        record: dict[str, Any] = {
            "role": self.role,
            "primary_provider": self.routes[0].provider,
            "primary_model": self.routes[0].model,
            "actual_provider": None,
            "actual_model": None,
            "fallback_used": False,
            "fallback_reason": None,
            "outcome": None,
            "attempts": [],
            "usage": None,
            "timestamp": _now(),
        }
        calls = _calls.get()
        if calls is not None:
            calls.append(record)
        last_error_response: httpx.Response | None = None
        for route_index, route in enumerate(self.routes):
            for attempt in range(self.policy.max_retries_per_provider + 1):
                started = time.perf_counter()
                result = yield ("send", self._build(request, body, route))
                entry: dict[str, Any] = {
                    "provider": route.provider,
                    "model": route.model,
                    "attempt": attempt + 1,
                    "timestamp": _now(),
                    "latency_s": time.perf_counter() - started,
                    "status_code": None,
                    "error_type": None,
                    "retry_after_s": None,
                    "daily_quota": False,
                    "message": None,
                }
                record["attempts"].append(entry)
                if isinstance(result, BaseException):
                    failure = classify_exception(result)
                    entry["error_type"] = failure.value
                    entry["message"] = self._redact(f"{type(result).__name__}: {result}")[:300]
                    if failure not in FALLBACK_ELIGIBLE:
                        record["outcome"] = "error"
                        raise result
                    retry_after = None
                else:
                    response, resp_body = result
                    entry["status_code"] = response.status_code
                    if response.status_code < 400:
                        record.update(
                            actual_provider=route.provider,
                            actual_model=route.model,
                            fallback_used=route_index > 0,
                            outcome="success",
                            usage=self._usage(resp_body),
                        )
                        return self._rebuild(request, response, resp_body)
                    text = resp_body.decode("utf-8", "replace")
                    failure = classify_status(response.status_code, text)
                    retry_after = retry_after_seconds(response.headers)
                    entry.update(
                        error_type=failure.value,
                        retry_after_s=retry_after,
                        daily_quota=is_daily_quota(text),
                        message=self._redact(text)[:300],
                    )
                    last_error_response = self._rebuild(request, response, resp_body)
                    if failure not in FALLBACK_ELIGIBLE:
                        record.update(actual_provider=route.provider, actual_model=route.model, outcome="error")
                        return last_error_response  # surfaced by the SDK as its usual exception
                if record["fallback_reason"] is None and route_index == 0:
                    record["fallback_reason"] = failure.value
                last_try = attempt == self.policy.max_retries_per_provider
                if last_try or entry["daily_quota"]:
                    break  # a daily quota will not reset within a retry
                wait = retry_after if retry_after is not None else self.policy.retry_backoff_s
                if wait > self.policy.max_retry_after_s:
                    break  # waiting this long would stall the run; the next provider is faster
                if wait > 0:
                    yield ("sleep", wait)
        record["outcome"] = EXHAUSTED
        if record["fallback_reason"] is None:
            record["fallback_reason"] = record["attempts"][0]["error_type"]
        return self._exhausted(request, record)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        plan = self._plan(request, request.read())
        step = next(plan)
        while True:
            kind, value = step
            try:
                if kind == "sleep":
                    self._sleep(value)
                    step = plan.send(None)
                    continue
                try:
                    response = self._sync_inner.handle_request(value)
                    result: Any = (response, response.read())
                except httpx.HTTPError as exc:
                    result = exc
                step = plan.send(result)
            except StopIteration as done:
                return done.value

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        plan = self._plan(request, await request.aread())
        step = next(plan)
        while True:
            kind, value = step
            try:
                if kind == "sleep":
                    await self._async_sleep(value)
                    step = plan.send(None)
                    continue
                try:
                    response = await self._async_inner.handle_async_request(value)
                    result: Any = (response, await response.aread())
                except httpx.HTTPError as exc:
                    result = exc
                step = plan.send(result)
            except StopIteration as done:
                return done.value

    def close(self) -> None:
        self._sync_inner.close()

    async def aclose(self) -> None:
        await self._async_inner.aclose()


def provider_health(records: list[dict[str, Any]], keys: tuple[str, ...] = ("provider_calls", "judge_provider_calls")) -> dict[str, Any]:
    """Per role and provider: requests, successes, rate limits, timeouts, server errors,
    fallbacks (requests this provider handed on), served_as_fallback, tokens (None if never reported)."""
    health: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        for key in keys:
            for call in record.get(key) or []:
                role = call.get("role", key)
                seen: set[str] = set()
                for attempt in call["attempts"]:
                    stats = health[role].setdefault(
                        attempt["provider"],
                        {"requests": 0, "successful_requests": 0, "rate_limits": 0, "timeouts": 0, "server_errors": 0,
                         "other_errors": 0, "fallbacks": 0, "served_as_fallback": 0, "input_tokens": None, "output_tokens": None},
                    )  # fmt: skip
                    stats["requests"] += 1
                    kind = attempt["error_type"]
                    if kind is None:
                        stats["successful_requests"] += 1
                    elif kind == FailureType.RATE_LIMIT:
                        stats["rate_limits"] += 1
                    elif kind == FailureType.TIMEOUT:
                        stats["timeouts"] += 1
                    elif kind in (FailureType.TRANSIENT_SERVER_ERROR, FailureType.PROVIDER_UNAVAILABLE):
                        stats["server_errors"] += 1
                    else:
                        stats["other_errors"] += 1
                    seen.add(attempt["provider"])
                for provider in seen:  # handed the request on: failed, and a later provider was tried
                    if provider != call["attempts"][-1]["provider"]:
                        health[role][provider]["fallbacks"] += 1
                if call.get("outcome") == "success" and call.get("fallback_used"):
                    health[role][call["actual_provider"]]["served_as_fallback"] += 1
                usage = call.get("usage")
                if usage and call.get("actual_provider"):
                    stats = health[role][call["actual_provider"]]
                    for k in ("input_tokens", "output_tokens"):
                        if usage.get(k) is not None:
                            stats[k] = (stats[k] or 0) + usage[k]
    return {role: dict(sorted(p.items())) for role, p in sorted(health.items())}


def render_health(health: dict[str, Any]) -> str:
    lines = ["Provider Health", "─" * 40]
    for role, providers in health.items():
        lines.append(f"[{role}]")
        for provider, s in providers.items():
            tokens = "n/a" if s["input_tokens"] is None else f"{s['input_tokens']} in / {s['output_tokens']} out"
            lines.append(
                f"  {provider:<12} requests {s['requests']:>4}  success {s['successful_requests']:>4}  rate limits {s['rate_limits']:>3}  "
                f"timeouts {s['timeouts']:>3}  server errors {s['server_errors']:>3}  fallbacks {s['fallbacks']:>3}  "
                f"served as fallback {s['served_as_fallback']:>3}  tokens {tokens}"
            )
    return "\n".join(lines)
