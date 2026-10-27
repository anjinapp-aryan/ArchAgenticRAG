"""Strict settings for the RAG system, parsed from the ``system`` section of a config.

The evaluation config keeps ``retrieval`` and ``chunking`` as free-form dicts. This
module is where they are validated, so a typo fails at graph build time, not mid-run.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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
    # "similarity" = dense top-k (the baseline). "mmr" = maximal marginal relevance, used only by
    # the Phase 3.1 control B2 (docs/PHASE-3.1-DESIGN.md).
    search_type: Literal["similarity", "mmr"] = "similarity"
    fetch_k: int | None = Field(default=None, ge=1, le=200)  # MMR candidate pool; MMR only
    embedding_dimension: int = Field(ge=1)
    qdrant: QdrantSettings

    @model_validator(mode="after")
    def _fetch_k_only_for_mmr(self) -> RetrievalSettings:
        if self.search_type == "mmr":
            if self.fetch_k is None or self.fetch_k < self.top_k:
                raise ValueError("search_type 'mmr' needs fetch_k >= top_k")
        elif self.fetch_k is not None:
            raise ValueError("fetch_k is only used with search_type 'mmr'")
        return self

    def search_kwargs(self) -> dict[str, int]:
        kwargs = {"k": self.top_k}
        if self.search_type == "mmr":
            kwargs["fetch_k"] = self.fetch_k
        return kwargs


class ChunkingSettings(_Strict):
    strategy: Literal["docling_hybrid"] = "docling_hybrid"
    tokenizer: str = Field(min_length=1)  # Hugging Face tokenizer id; should match the embedding model
    max_tokens: int = Field(ge=32, le=8192)
    merge_peers: bool = True


class DecompositionSettings(_Strict):
    """Phase 3.1 query decomposition (docs/PHASE-3.1-DESIGN.md)."""

    max_sub_questions: int = Field(default=3, ge=1, le=3)  # includes the original question
    max_context_chunks: int = Field(default=8, ge=1, le=50)  # cap after the merge


class RAGSettings(_Strict):
    generator: LLMSettings
    embedding: EmbeddingSettings
    reranker: None = None  # Basic RAG has no reranker; later phases change this
    retrieval: RetrievalSettings
    chunking: ChunkingSettings
    decomposition: DecompositionSettings | None = None  # Phase 3.1 graph only


class SettingsError(ValueError):
    pass


def parse_settings(system: dict[str, Any]) -> RAGSettings:
    try:
        return RAGSettings.model_validate(system)
    except ValidationError as exc:
        raise SettingsError(f"invalid RAG system settings:\n{exc}") from exc
