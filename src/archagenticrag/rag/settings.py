"""Strict settings for the RAG system, parsed from the ``system`` section of a config.

The evaluation config keeps ``retrieval`` and ``chunking`` as free-form dicts. This
module is where they are validated, so a typo fails at graph build time, not mid-run.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from archagenticrag.providers import PROVIDERS, ProviderStrategy


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


class SparseSettings(_Strict):
    """Experiment 02 sparse branch: FastEmbed BM25 term weights; Qdrant applies IDF at query time."""

    provider: Literal["local"] = "local"  # FastEmbed SparseTextEmbedding, CPU, no key
    model: Literal["Qdrant/bm25"] = "Qdrant/bm25"
    modifier: Literal["idf"] = "idf"  # required by Qdrant/bm25 (fastembed Bm25 docstring)


class RetrievalSettings(_Strict):
    # "dense" = the baseline. "hybrid" = Experiment 02: dense + BM25, each branch limited to top_k,
    # fused by Qdrant RRF to top_k (langchain-qdrant RetrievalMode.HYBRID).
    mode: Literal["dense", "hybrid"] = "dense"
    sparse: SparseSettings | None = None  # hybrid only
    fusion: Literal["rrf"] | None = None  # hybrid only; Qdrant FusionQuery(Fusion.RRF)
    top_k: int = Field(ge=1, le=50)
    # "similarity" = dense top-k (the baseline). "mmr" = maximal marginal relevance, used only by
    # the Phase 3.1 control B2 (docs/PHASE-3.1-DESIGN.md).
    search_type: Literal["similarity", "mmr"] = "similarity"
    fetch_k: int | None = Field(default=None, ge=1, le=200)  # MMR candidate pool; MMR only
    embedding_dimension: int = Field(ge=1)
    qdrant: QdrantSettings

    @model_validator(mode="after")
    def _hybrid_needs_sparse_and_fusion(self) -> RetrievalSettings:
        if self.mode == "hybrid":
            if self.sparse is None or self.fusion is None:
                raise ValueError("retrieval.mode 'hybrid' needs retrieval.sparse and retrieval.fusion")
            if self.search_type != "similarity":
                raise ValueError("retrieval.mode 'hybrid' supports only search_type 'similarity'")
        elif self.sparse is not None or self.fusion is not None:
            raise ValueError("retrieval.sparse and retrieval.fusion are only used with mode 'hybrid'")
        return self

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
    provider_strategy: ProviderStrategy | None = None  # generator provider pool; None = single provider


class SettingsError(ValueError):
    pass


def parse_settings(system: dict[str, Any]) -> RAGSettings:
    try:
        return RAGSettings.model_validate(system)
    except ValidationError as exc:
        raise SettingsError(f"invalid RAG system settings:\n{exc}") from exc
