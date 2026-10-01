from __future__ import annotations

import pytest

from archagenticrag.rag.settings import SettingsError, parse_settings


def test_baseline_system_settings_parse(system):
    settings = parse_settings(system)
    assert settings.retrieval.top_k == 4
    assert settings.retrieval.embedding_dimension == 384
    assert settings.retrieval.qdrant.url == "http://localhost:6333"
    assert settings.embedding.provider == "local"
    assert settings.chunking.strategy == "docling_hybrid"
    assert settings.reranker is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda s: s["generator"].update(provider="acme"), "unknown LLM provider"),
        (lambda s: s["embedding"].update(provider="gemini"), "embedding"),
        (lambda s: s.update(reranker={"provider": "local", "model": "x"}), "reranker"),
        (lambda s: s["retrieval"].update(top_k=0), "top_k"),
        (lambda s: s["retrieval"].update(search_type="hybrid"), "search_type"),
        (lambda s: s["retrieval"].pop("embedding_dimension"), "embedding_dimension"),
        (lambda s: s["retrieval"]["qdrant"].update(collection="bad name!"), "collection"),
        (lambda s: s["retrieval"].update(rerank=True), "rerank"),
        (lambda s: s["chunking"].update(strategy="recursive_character"), "strategy"),
        (lambda s: s["chunking"].update(max_tokens=10), "max_tokens"),
    ],
)
def test_invalid_settings_fail_clearly(system, mutate, message):
    mutate(system)
    with pytest.raises(SettingsError, match=message):
        parse_settings(system)


def test_ollama_needs_no_api_key(monkeypatch):
    from archagenticrag.providers import resolve

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert resolve("ollama") == ("http://localhost:11434/v1", "not-needed")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434/v1")
    assert resolve("ollama")[0] == "http://gpu-box:11434/v1"
