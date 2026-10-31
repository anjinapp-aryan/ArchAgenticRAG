"""Experiment 02 hybrid retrieval (docs/EXPERIMENT-02-HYBRID-RETRIEVAL.md). Offline: fake LLM,
fake dense and sparse embeddings, in-memory Qdrant."""

from __future__ import annotations

import copy
import zlib

import pytest
import yaml
from langchain_qdrant import SparseEmbeddings, SparseVector

from archagenticrag.evaluation.config import TargetRef, load_config
from archagenticrag.evaluation.target import run_target
from archagenticrag.graphs.basic_rag import HYBRID_METHOD, build_graph
from archagenticrag.rag.settings import SettingsError, parse_settings
from archagenticrag.rag.vector_store import SPARSE_VECTOR_NAME, VectorStoreError, index_documents, open_store

from .conftest import REPO_ROOT
from .test_basic_rag import RecordingChatModel

HYBRID = {"mode": "hybrid", "sparse": {"provider": "local", "model": "Qdrant/bm25", "modifier": "idf"}, "fusion": "rrf"}


class FakeSparse(SparseEmbeddings):
    """Bag of lower-case words, hashed to stable indices (stands in for FastEmbed BM25)."""

    def _vector(self, text: str) -> SparseVector:
        counts: dict[int, float] = {}
        for word in text.lower().split():
            index = zlib.crc32(word.strip(".,?:").encode()) % 100_000
            counts[index] = counts.get(index, 0.0) + 1.0
        return SparseVector(indices=list(counts), values=list(counts.values()))

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> SparseVector:
        return self._vector(text)


@pytest.fixture
def hybrid_system(system) -> dict:
    hybrid = copy.deepcopy(system)  # leave the baseline `system` fixture untouched
    hybrid["retrieval"].update(HYBRID)
    hybrid["retrieval"]["qdrant"]["collection"] = "peps_test_hybrid"
    return hybrid


@pytest.fixture
def hybrid_index(memory_client, hybrid_system, fake_embeddings, sample_chunks):
    index_documents(memory_client, parse_settings(hybrid_system), fake_embeddings, sample_chunks, {"corpus_id": "test"}, sparse_embeddings=FakeSparse())
    return memory_client


def _graph(client, system, fake_embeddings):
    llm = RecordingChatModel(responses=["79 characters."], seen=[])
    return build_graph(system=system, client=client, embeddings=fake_embeddings, llm=llm, sparse_embeddings=FakeSparse())


# configuration


def test_hybrid_settings_validation(system):
    assert parse_settings(system).retrieval.mode == "dense"  # baseline default
    for bad in (
        {"mode": "hybrid"},  # no sparse / fusion
        {"mode": "hybrid", "sparse": HYBRID["sparse"]},  # no fusion
        {"sparse": HYBRID["sparse"]},  # sparse without hybrid
        {"fusion": "rrf"},  # fusion without hybrid
        {**HYBRID, "fusion": "dbsf"},  # only RRF is configured
        {**HYBRID, "sparse": {"model": "prithivida/Splade_PP_en_v1"}},  # only BM25
        {**HYBRID, "search_type": "mmr", "fetch_k": 20},  # MMR is not part of this experiment
    ):
        broken = copy.deepcopy(system)
        broken["retrieval"].update(bad)
        with pytest.raises(SettingsError):
            parse_settings(broken)


def test_experiment_02_config_differs_from_baseline_only_in_retrieval_mode_and_collection():
    def load(name):
        return yaml.safe_load((REPO_ROOT / "eval/configs" / name).read_text(encoding="utf-8"))

    base, exp = load("baseline-basic-rag.yaml"), load("exp02-hybrid-bm25.yaml")
    diffs = {}

    def walk(a, b, path=""):
        for key in set(a) | set(b):
            p = f"{path}.{key}" if path else key
            if isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
                walk(a[key], b[key], p)
            elif a.get(key) != b.get(key):
                diffs[p] = b.get(key)

    walk(base, exp)
    assert diffs == {
        "run_name": "exp02-hybrid-bm25",
        "system.retrieval.mode": "hybrid",
        "system.retrieval.sparse": {"provider": "local", "model": "Qdrant/bm25", "modifier": "idf"},
        "system.retrieval.fusion": "rrf",
        "system.retrieval.qdrant.collection": "peps_v1_bge_small_docling_480_hybrid_bm25",
    }
    # same graph, generator, prompt, embedding, chunking, top_k, judge, metrics as the baseline
    config = load_config(REPO_ROOT / "eval/configs/exp02-hybrid-bm25.yaml")
    assert config.target.factory == "archagenticrag.graphs.basic_rag:build_graph"
    assert load_config(REPO_ROOT / "eval/configs/baseline-basic-rag.yaml").fingerprint() == "63bf3b5f990cc9e5"


# index safety


def test_hybrid_collection_has_dense_and_idf_sparse_vectors(hybrid_index):
    info = hybrid_index.get_collection("peps_test_hybrid")
    assert info.config.params.vectors.size == 384  # same unnamed dense vector as the baseline
    sparse = info.config.params.sparse_vectors[SPARSE_VECTOR_NAME]
    assert str(sparse.modifier).lower().endswith("idf")
    meta = info.config.metadata
    assert meta["retrieval_mode"] == "hybrid" and meta["sparse"]["model"] == "Qdrant/bm25"


def test_a_hybrid_config_cannot_replace_a_dense_collection(memory_client, system, hybrid_system, fake_embeddings, sample_chunks):
    settings = parse_settings(system)
    index_documents(memory_client, settings, fake_embeddings, sample_chunks, {"corpus_id": "test"})
    hybrid_system["retrieval"]["qdrant"]["collection"] = settings.retrieval.qdrant.collection  # misconfigured: baseline name
    with pytest.raises(VectorStoreError, match="refusing to replace"):
        index_documents(memory_client, parse_settings(hybrid_system), fake_embeddings, sample_chunks, {}, sparse_embeddings=FakeSparse())
    assert memory_client.count(settings.retrieval.qdrant.collection, exact=True).count == len(sample_chunks)
    assert "retrieval_mode" not in memory_client.get_collection(settings.retrieval.qdrant.collection).config.metadata


def test_open_store_refuses_a_mode_mismatch(hybrid_index, hybrid_system, fake_embeddings):
    dense = copy.deepcopy(hybrid_system)
    for key in ("mode", "sparse", "fusion"):
        dense["retrieval"].pop(key)
    with pytest.raises(VectorStoreError, match="hybrid retrieval"):
        open_store(hybrid_index, parse_settings(dense), fake_embeddings)


# retrieval


def test_hybrid_query_prefetches_dense_and_sparse_top_k_and_fuses_with_rrf(hybrid_index, hybrid_system, fake_embeddings, monkeypatch):
    calls = []
    original = hybrid_index.query_points
    monkeypatch.setattr(hybrid_index, "query_points", lambda *a, **kw: calls.append(kw) or original(*a, **kw))
    graph = _graph(hybrid_index, hybrid_system, fake_embeddings)
    out = graph.invoke({"question": "What is the walrus operator NAME := expr?"})

    (call,) = calls
    assert [(p.using, p.limit) for p in call["prefetch"]] == [("", 4), (SPARSE_VECTOR_NAME, 4)]  # per-branch k = top_k
    assert str(call["query"].fusion).lower().endswith("rrf")
    assert call["limit"] == 4  # final fused list = top_k, same length as the baseline
    assert len(out["documents"]) == 3  # only 3 chunks in the test index
    assert {d.metadata["chunk_id"] for d in out["documents"]} == {"pep-0008#000", "pep-0020#000", "pep-0572#000"}


async def test_hybrid_retrieval_trace_records_rank_ids_method_and_no_score(hybrid_index, hybrid_system, fake_embeddings):
    graph = _graph(hybrid_index, hybrid_system, fake_embeddings)
    res = await run_target(graph, TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph"), "walrus operator NAME := expr")
    assert res.error is None
    assert [r["rank"] for r in res.retrieval_results] == [1, 2, 3]
    assert all(r["chunk_id"] and r["doc_id"] for r in res.retrieval_results)
    assert {r["method"] for r in res.retrieval_results} == {HYBRID_METHOD}
    assert all(r["score"] is None for r in res.retrieval_results)  # the retriever drops the RRF score
    (call,) = res.retrieval_calls
    assert call["method"] == HYBRID_METHOD and call["latency_s"] >= 0


def test_sparse_branch_finds_an_exact_token(hybrid_index, hybrid_system, fake_embeddings):
    """Only pep-0572 contains "walrus", so the sparse branch ranks it first. Its RRF score is at
    least that of the dense branch's first hit, so it is in the fused top 2 whatever dense does."""
    hybrid_system["retrieval"]["top_k"] = 2
    graph = _graph(hybrid_index, hybrid_system, fake_embeddings)
    out = graph.invoke({"question": "walrus"})
    assert "pep-0572#000" in [d.metadata["chunk_id"] for d in out["documents"]]


def test_dense_baseline_graph_is_unchanged(memory_client, system, fake_embeddings, sample_chunks, monkeypatch):
    index_documents(memory_client, parse_settings(system), fake_embeddings, sample_chunks, {"corpus_id": "test"})
    calls = []
    original = memory_client.query_points
    monkeypatch.setattr(memory_client, "query_points", lambda *a, **kw: calls.append(kw) or original(*a, **kw))
    llm = RecordingChatModel(responses=["x"], seen=[])
    graph = build_graph(system=system, client=memory_client, embeddings=fake_embeddings, llm=llm)
    graph.invoke({"question": "line length"})
    (call,) = calls
    assert call.get("prefetch") is None and call["limit"] == 4  # plain dense top-4 search
