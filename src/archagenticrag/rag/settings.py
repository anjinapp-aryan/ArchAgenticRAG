"""Strict settings for the RAG system, parsed from the ``system`` section of a config.

The evaluation config keeps ``retrieval`` and ``chunking`` as free-form dicts. This
module is where they are validated, so a typo fails at graph build time, not mid-run.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from archagenticrag.providers import PROVIDERS


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMSettings(_Strict):
    provider: str
    model: str = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @field_validator("provider")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in PROVIDERS:
            raise ValueError(f"unknown LLM provider {value!r}; known: {sorted(PROVIDERS)}")
        return value


class EmbeddingSettings(_Strict):
    # "local" = FastEmbed (ONNX, runs on CPU, no API key, no server).
    provider: Literal["local"]
    model: str = Field(min_length=1)
    temperature: None = None  # accepted for config symmetry, never used


class QdrantSettings(_Strict):
    url: str = "http://localhost:6333"
    collection: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    api_key_env: str | None = None  # only for a secured / cloud Qdrant


class RetrievalSettings(_Strict):
    top_k: int = Field(ge=1, le=50)
    search_type: Literal["similarity"] = "similarity"  # Basic RAG: dense similarity only
    embedding_dimension: int = Field(ge=1)
    qdrant: QdrantSettings


class ChunkingSettings(_Strict):
    strategy: Literal["docling_hybrid"] = "docling_hybrid"
    tokenizer: str = Field(min_length=1)  # Hugging Face tokenizer id; should match the embedding model
    max_tokens: int = Field(ge=32, le=8192)
    merge_peers: bool = True


class RAGSettings(_Strict):
    generator: LLMSettings
    embedding: EmbeddingSettings
    reranker: None = None  # Basic RAG has no reranker; later phases change this
    retrieval: RetrievalSettings
    chunking: ChunkingSettings


class SettingsError(ValueError):
    pass


def parse_settings(system: dict[str, Any]) -> RAGSettings:
    try:
        return RAGSettings.model_validate(system)
    except ValidationError as exc:
        raise SettingsError(f"invalid RAG system settings:\n{exc}") from exc
