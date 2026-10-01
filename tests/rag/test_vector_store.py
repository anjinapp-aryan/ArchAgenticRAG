from __future__ import annotations

import pytest

from archagenticrag.rag.settings import parse_settings
from archagenticrag.rag.vector_store import VectorStoreError, index_documents, open_store, point_id


def _index(memory_client, system, fake_embeddings, sample_chunks):
    settings = parse_settings(system)
    meta = index_documents(memory_client, settings, fake_embeddings, sample_chunks, {"corpus_id": "test"})
    return settings, meta


def test_collection_is_created_with_index_metadata(memory_client, system, fake_embeddings, sample_chunks):
    settings, meta = _index(memory_client, system, fake_embeddings, sample_chunks)
    name = settings.retrieval.qdrant.collection
    assert memory_client.count(name, exact=True).count == 3
    stored = memory_client.get_collection(name).config.metadata
    assert stored["embedding_dimension"] == 384
    assert stored["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert stored["chunks"] == 3 and stored["corpus_id"] == "test"


def test_reindexing_is_idempotent(memory_client, system, fake_embeddings, sample_chunks):
    settings, _ = _index(memory_client, system, fake_embeddings, sample_chunks)
    _index(memory_client, system, fake_embeddings, sample_chunks)
    assert memory_client.count(settings.retrieval.qdrant.collection, exact=True).count == 3
    assert point_id("pep-0008#000") == point_id("pep-0008#000")


def test_dimension_mismatch_is_rejected(memory_client, system, sample_chunks):
    from langchain_core.embeddings import DeterministicFakeEmbedding

    with pytest.raises(VectorStoreError, match="384"):
        index_documents(memory_client, parse_settings(system), DeterministicFakeEmbedding(size=768), sample_chunks, {})


def test_open_store_requires_existing_collection(memory_client, system, fake_embeddings):
    with pytest.raises(VectorStoreError, match="does not exist.*ingest"):
        open_store(memory_client, parse_settings(system), fake_embeddings)


def test_open_store_rejects_index_built_with_other_settings(memory_client, system, fake_embeddings, sample_chunks):
    _index(memory_client, system, fake_embeddings, sample_chunks)
    system["embedding"]["model"] = "BAAI/bge-base-en-v1.5"
    with pytest.raises(VectorStoreError, match="indexed with"):
        open_store(memory_client, parse_settings(system), fake_embeddings)
    system["embedding"]["model"] = "BAAI/bge-small-en-v1.5"
    system["chunking"]["max_tokens"] = 256
    with pytest.raises(VectorStoreError, match="chunked with"):
        open_store(memory_client, parse_settings(system), fake_embeddings)


def test_similarity_search_returns_top_k(memory_client, system, fake_embeddings, sample_chunks):
    settings, _ = _index(memory_client, system, fake_embeddings, sample_chunks)
    store, _ = open_store(memory_client, settings, fake_embeddings)
    # DeterministicFakeEmbedding hashes the text, so the exact text is its own nearest neighbour.
    hits = store.similarity_search(sample_chunks[2].page_content, k=2)
    assert len(hits) == 2
    assert hits[0].metadata["doc_id"] == "pep-0572"
