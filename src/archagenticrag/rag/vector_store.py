"""Qdrant vector store: client, collection lifecycle, indexing.

Vector search, payload storage and dimension validation are done by qdrant-client and
langchain-qdrant. The collection-size guard follows the pattern in
GiovanniPasq/agentic-rag-for-dummies (MIT; see THIRD_PARTY_NOTICES.md). Here it is
reimplemented for a Qdrant server and dense-only retrieval.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from archagenticrag.rag.settings import EmbeddingSettings, QdrantSettings, RAGSettings

# Stable namespace so re-indexing the same chunk always gives the same point id.
_POINT_NAMESPACE = uuid.UUID("6f1c7d36-0a51-4c57-9b8e-2d6c3b0b7a11")


class VectorStoreError(RuntimeError):
    pass


def make_client(settings: QdrantSettings):
    from qdrant_client import QdrantClient

    api_key = os.environ.get(settings.api_key_env) if settings.api_key_env else None
    return QdrantClient(url=settings.url, api_key=api_key)


def make_embeddings(settings: EmbeddingSettings) -> Embeddings:
    """Local embeddings via FastEmbed (ONNX on CPU, model downloaded once and cached)."""
    from langchain_community.embeddings import FastEmbedEmbeddings

    return FastEmbedEmbeddings(model_name=settings.model)


def embedding_dimension(embeddings: Embeddings) -> int:
    return len(embeddings.embed_query("dimension probe"))


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


def index_documents(
    client: Any,
    settings: RAGSettings,
    embeddings: Embeddings,
    documents: list[Document],
    index_metadata: dict[str, Any],
    *,
    recreate: bool = True,
) -> dict[str, Any]:
    """(Re)create the collection and upsert all chunks. Returns the stored index metadata."""
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client.http import models as qm

    name = settings.retrieval.qdrant.collection
    dim = embedding_dimension(embeddings)
    if dim != settings.retrieval.embedding_dimension:
        raise VectorStoreError(
            f"{settings.embedding.model} produces {dim}-dimensional vectors, "
            f"but the config says retrieval.embedding_dimension={settings.retrieval.embedding_dimension}"
        )
    if recreate and client.collection_exists(name):
        client.delete_collection(name)
    metadata = {
        **index_metadata,
        "embedding_model": settings.embedding.model,
        "embedding_provider": settings.embedding.provider,
        "embedding_dimension": dim,
        "chunking": settings.chunking.model_dump(),
        "chunks": len(documents),
        "indexed_at": datetime.now(UTC).isoformat(),
    }
    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        metadata=metadata,
    )
    store = QdrantVectorStore(client=client, collection_name=name, embedding=embeddings)
    store.add_documents(documents, ids=[point_id(d.metadata["chunk_id"]) for d in documents])
    count = client.count(name, exact=True).count
    if count != len(documents):
        raise VectorStoreError(f"indexed {count} points, expected {len(documents)}")
    return metadata


def open_store(client: Any, settings: RAGSettings, embeddings: Embeddings):
    """Open an existing, non-empty collection whose metadata matches the settings."""
    from langchain_qdrant import QdrantVectorStore

    name = settings.retrieval.qdrant.collection
    if not client.collection_exists(name):
        raise VectorStoreError(
            f"Qdrant collection {name!r} does not exist at {settings.retrieval.qdrant.url}. "
            "Run: python -m archagenticrag.rag.ingest <config>"
        )
    info = client.get_collection(name)
    meta = info.config.metadata or {}
    if meta.get("embedding_model") != settings.embedding.model:
        raise VectorStoreError(
            f"collection {name!r} was indexed with {meta.get('embedding_model')!r}, "
            f"config uses {settings.embedding.model!r}; re-run ingestion"
        )
    if meta.get("chunking") != settings.chunking.model_dump():
        raise VectorStoreError(f"collection {name!r} was chunked with {meta.get('chunking')}; re-run ingestion")
    if not client.count(name, exact=True).count:
        raise VectorStoreError(f"collection {name!r} is empty; re-run ingestion")
    # validate_collection_config (langchain-qdrant) checks vector size and distance.
    store = QdrantVectorStore(client=client, collection_name=name, embedding=embeddings, validate_collection_config=True)
    return store, meta
