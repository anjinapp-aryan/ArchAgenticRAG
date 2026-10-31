"""Live smoke test of multi-provider fallback: two tiny real requests, no forced real 429.

Run with: pytest -m live -k provider_fallback   (needs GEMINI_API_KEY and GROQ_API_KEY in .env)
The second test simulates Gemini's rate limit locally and lets the request reach Groq for real.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from archagenticrag.provider_fallback import collect_provider_calls
from archagenticrag.providers import chat_model

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.live


@pytest.fixture
def strategy():
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    if not (os.environ.get("GEMINI_API_KEY") and os.environ.get("GROQ_API_KEY")):
        pytest.skip("needs GEMINI_API_KEY and GROQ_API_KEY")
    return {
        "mode": "fallback",
        "fallbacks": [{"provider": "groq", "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")}],
        "max_retries_per_provider": 0,
        "retry_backoff_s": 0,
    }


def _gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


class GeminiRateLimited(httpx.BaseTransport):
    """Answers Gemini requests with a local 429; every other request goes to the real network."""

    def __init__(self) -> None:
        self.real = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "generativelanguage.googleapis.com":
            body = json.dumps({"error": {"message": "simulated rate limit (local, not sent)"}}).encode()
            return httpx.Response(429, headers={"content-type": "application/json"}, content=body)
        return self.real.handle_request(request)


def test_primary_provider_success(strategy):
    llm = chat_model("gemini", _gemini_model(), 0, max_tokens=256, strategy=strategy)
    with collect_provider_calls() as calls:
        reply = llm.invoke("Reply with the single word OK.").content
    assert reply.strip()
    (call,) = calls
    assert call["outcome"] == "success" and call["actual_provider"] == "gemini" and call["fallback_used"] is False


def test_simulated_primary_rate_limit_falls_back_to_a_real_provider(strategy):
    llm = chat_model("gemini", _gemini_model(), 0, max_tokens=256, strategy=strategy, inner_transport=GeminiRateLimited())
    with collect_provider_calls() as calls:
        reply = llm.invoke("Reply with the single word OK.").content
    assert reply.strip()
    (call,) = calls
    assert (call["actual_provider"], call["fallback_used"], call["fallback_reason"]) == ("groq", True, "RATE_LIMIT")
    assert [a["provider"] for a in call["attempts"]] == ["gemini", "groq"]
    assert call["usage"]["input_tokens"] > 0  # Groq reports usage
