"""Experiment 03 reranking (docs/EXPERIMENT-03-RERANKING-AUDIT.md). Offline: fake LLM, embeddings,
sparse model and cross-encoder, in-memory Qdrant."""

from __future__ import annotations

import copy

import pytest
import yaml
from langchain_core.documents import Document

from archagenticrag.evaluation.benchmark import _candidate_stage
from archagenticrag.evaluation.config import TargetRef, load_config
from archagenticrag.evaluation.ranking import candidate_view, ranked_chunk_ids, run_ranking
from archagenticrag.evaluation.relevance import text_sha256
from archagenticrag.evaluation.target import run_target
from archagenticrag.graphs.basic_rag import HYBRID_METHOD, build_graph
from archagenticrag.rag.rerank import FastEmbedRerank
from archagenticrag.rag.settings import SettingsError, parse_settings
from archagenticrag.rag.vector_store import index_documents

from .conftest import REPO_ROOT
from .test_basic_rag import RecordingChatModel
from .test_hybrid_rag import HYBRID, FakeSparse

MODEL = "jinaai/jina-reranker-v1-tiny-en"
RERANK_METHOD = f"rerank({MODEL})"


class FakeEncoder:
    """Scores a document by the number in its text, so the expected order is known. Records its input."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, documents: list[str]):
        self.calls.append((query, list(documents)))
        return [float(text.rsplit(" ", 1)[-1]) for text in documents]


def _chunks(n: int = 30) -> list[Document]:
    return [
        Document(page_content=f"walrus operator chunk {i}", metadata={"doc_id": f"pep-{i % 3:04d}", "chunk_id": f"pep-{i % 3:04d}#{i:03d}"})
        for i in range(n)
    ]


@pytest.fixture
def rerank_system(system) -> dict:
    s = copy.deepcopy(system)
    s["retrieval"].update(HYBRID, candidate_k=20)
    s["retrieval"]["qdrant"]["collection"] = "peps_test_rerank"
    s["reranker"] = {"provider": "local", "model": MODEL}
    return s


@pytest.fixture
def index(memory_client, rerank_system, fake_embeddings):
    index_documents(memory_client, parse_settings(rerank_system), fake_embeddings, _chunks(), {"corpus_id": "test"}, sparse_embeddings=FakeSparse())
    return memory_client


def _graph(client, system, embeddings, encoder):
    llm = RecordingChatModel(responses=["answer"], seen=[])
    return build_graph(system=system, client=client, embeddings=embeddings, llm=llm, sparse_embeddings=FakeSparse(), encoder=encoder)


# compressor


def _doc(text: str, chunk_id: str) -> Document:
    return Document(page_content=text, metadata={"chunk_id": chunk_id, "doc_id": "d"})


def test_compressor_orders_by_score_keeps_metadata_and_cuts_to_top_n():
    docs = [_doc("a 1", "c1"), _doc("b 3", "c2"), _doc("c 2", "c3")]
    out = FastEmbedRerank(encoder=FakeEncoder(), top_n=2).compress_documents(docs, "q")
    assert [d.metadata["chunk_id"] for d in out] == ["c2", "c3"]
    assert [d.metadata["relevance_score"] for d in out] == [3.0, 2.0]
    assert out[0].metadata["doc_id"] == "d" and "relevance_score" not in docs[1].metadata  # input untouched


def test_equal_scores_keep_candidate_order():
    docs = [_doc("a 1", "c1"), _doc("b 1", "c2"), _doc("c 1", "c3")]
    out = FastEmbedRerank(encoder=FakeEncoder(), top_n=2).compress_documents(docs, "q")
    assert [d.metadata["chunk_id"] for d in out] == ["c1", "c2"]


def test_compressor_handles_few_or_no_candidates_and_rejects_a_bad_encoder():
    encoder = FakeEncoder()
    assert FastEmbedRerank(encoder=encoder, top_n=4).compress_documents([], "q") == []
    assert encoder.calls == []
    assert len(FastEmbedRerank(encoder=encoder, top_n=4).compress_documents([_doc("a 1", "c1")], "q")) == 1

    class Short:
        def rerank(self, query, documents):
            return [1.0]

    with pytest.raises(ValueError, match="1 scores for 2"):
        FastEmbedRerank(encoder=Short(), top_n=1).compress_documents([_doc("a 1", "c1"), _doc("b 2", "c2")], "q")


# settings and config


def test_reranker_settings_validation(rerank_system, system):
    assert parse_settings(system).reranker is None
    assert parse_settings(system).retrieval.search_kwargs() == {"k": 4}  # baseline
    assert parse_settings(rerank_system).retrieval.search_kwargs() == {"k": 20}
    no_reranker = copy.deepcopy(rerank_system)
    no_reranker["reranker"] = None
    too_small = copy.deepcopy(rerank_system)
    too_small["retrieval"]["candidate_k"] = 4
    missing = copy.deepcopy(rerank_system)
    del missing["retrieval"]["candidate_k"]
    remote = copy.deepcopy(rerank_system)
    remote["reranker"]["provider"] = "groq"
    for bad in (no_reranker, too_small, missing, remote):
        with pytest.raises(SettingsError):
            parse_settings(bad)


def test_experiment_03_config_differs_from_02_only_in_candidate_depth_and_reranker():
    def load(name):
        return yaml.safe_load((REPO_ROOT / "eval/configs" / name).read_text(encoding="utf-8"))

    diffs = {}

    def walk(a, b, path=""):
        for key in set(a) | set(b):
            p = f"{path}.{key}" if path else key
            if isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
                walk(a[key], b[key], p)
            elif a.get(key) != b.get(key):
                diffs[p] = b.get(key)

    walk(load("exp02-hybrid-bm25.yaml"), load("exp03-hybrid-rerank.yaml"))
    assert diffs == {
        "run_name": "exp03-hybrid-rerank",
        "system.reranker": {"provider": "local", "model": MODEL},
        "system.retrieval.candidate_k": 20,
    }
    assert load_config(REPO_ROOT / "eval/configs/baseline-basic-rag.yaml").fingerprint() == "63bf3b5f990cc9e5"
    assert load_config(REPO_ROOT / "eval/configs/exp02-hybrid-bm25.yaml").fingerprint() == "690aff0c9e3997bd"


def test_a_config_without_reranker_builds_no_encoder(index, rerank_system, fake_embeddings):
    plain = copy.deepcopy(rerank_system)
    plain["reranker"] = None
    del plain["retrieval"]["candidate_k"]
    out = _graph(index, plain, fake_embeddings, encoder=None).invoke({"question": "walrus"})  # would fail if it loaded a model
    assert len(out["documents"]) == 4 and "relevance_score" not in out["documents"][0].metadata


# graph


def test_query_fetches_candidate_k_and_generator_gets_top_k(index, rerank_system, fake_embeddings, monkeypatch):
    calls = []
    original = index.query_points
    monkeypatch.setattr(index, "query_points", lambda *a, **kw: calls.append(kw) or original(*a, **kw))
    encoder = FakeEncoder()
    out = _graph(index, rerank_system, fake_embeddings, encoder).invoke({"question": "walrus operator"})

    (call,) = calls
    assert [p.limit for p in call["prefetch"]] == [20, 20] and call["limit"] == 20
    ((query, candidates),) = encoder.calls
    assert query == "walrus operator" and len(candidates) == 20  # the whole pool, not 4
    assert len(out["documents"]) == 4
    ids = [d.metadata["chunk_id"] for d in out["documents"]]
    assert len(set(ids)) == 4
    scores = [d.metadata["relevance_score"] for d in out["documents"]]
    assert scores == sorted(scores, reverse=True) and scores[0] == max(float(c.rsplit(" ", 1)[-1]) for c in candidates)
    assert all(d.metadata["doc_id"] and d.metadata["chunk_id"] for d in out["documents"])


async def test_trace_separates_candidate_and_final_stages(index, rerank_system, fake_embeddings):
    graph = _graph(index, rerank_system, fake_embeddings, FakeEncoder())
    res = await run_target(graph, TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph"), "walrus operator")
    assert res.error is None
    assert graph.eval_metadata["reranker"] == {"provider": "local", "model": MODEL, "temperature": None, "candidate_k": 20}

    by_stage = {c["retrieval_stage"]: c for c in res.retrieval_calls}
    assert set(by_stage) == {"candidate", "final"}
    assert by_stage["candidate"]["method"] == HYBRID_METHOD and len(by_stage["candidate"]["results"]) == 20
    assert by_stage["final"]["method"] == RERANK_METHOD and len(by_stage["final"]["results"]) == 4
    assert all(r["score"] is None for r in by_stage["candidate"]["results"])

    candidate_ranks = {r["chunk_id"]: r["rank"] for r in by_stage["candidate"]["results"]}
    assert [r["rank"] for r in res.retrieval_results] == [1, 2, 3, 4]
    for hit in res.retrieval_results:
        assert hit["method"] == RERANK_METHOD and hit["score_key"] == "relevance_score" and hit["score"] is not None
        assert hit["candidate_rank"] == candidate_ranks[hit["chunk_id"]] and hit["candidate_method"] == HYBRID_METHOD


# metrics: candidate retrieval vs reranking


def test_a_candidate_failure_is_distinguished_from_a_reranker_failure():
    def results(*ids):
        return [{"rank": i + 1, "chunk_id": c, "doc_id": c.split("#")[0]} for i, c in enumerate(ids)]

    pool_q1 = ["x#1", "x#2", "x#3", "x#4", "a#0", "x#6"]  # relevant at rank 5: only the reranker can fix it
    pool_q2 = ["x#1", "x#2", "x#3", "x#4", "x#5", "x#6"]  # relevant absent: no reranker can fix it
    pool_q3 = ["c#0", "x#2", "x#3", "x#4", "x#5", "x#6"]  # relevant first: the reranker pushes it out
    records = [
        {"id": "Q1", "retrieval_results": results("a#0", "x#1", "x#2", "x#3"), "retrieval_calls": [{"retrieval_stage": "candidate", "results": results(*pool_q1)}]},
        {"id": "Q2", "retrieval_results": results("x#1", "x#2", "x#3", "x#4"), "retrieval_calls": [{"retrieval_stage": "candidate", "results": results(*pool_q2)}]},
        {"id": "Q3", "retrieval_results": results("x#2", "x#3", "x#4", "x#5"), "retrieval_calls": [{"retrieval_stage": "candidate", "results": results(*pool_q3)}]},
    ]
    qrels = {
        "chunk_set": {"collection": "c"},
        "chunk_catalog": {"a#0": {"doc_id": "a", "sha256": text_sha256("A")}},
        "queries": {
            "Q1": {"category": "A", "expected_behavior": "answer", "chunk_relevance": {"a#0": 1}, "doc_relevance": {"a": 1}},
            "Q2": {"category": "A", "expected_behavior": "answer", "chunk_relevance": {"b#0": 1}, "doc_relevance": {"b": 1}},
            "Q3": {"category": "A", "expected_behavior": "answer", "chunk_relevance": {"c#0": 1}, "doc_relevance": {"c": 1}},
        },
    }
    final = run_ranking(records, qrels, (4, 20))
    stage = _candidate_stage(records, qrels, {"Q1", "Q2", "Q3"}, final, (4, 20), 4)

    assert stage["pool"]["chunk"]["mean"]["recall@20"] == pytest.approx(2 / 3)  # Q2's evidence never entered the pool
    assert stage["top_k_without_rerank"]["chunk"]["mean"]["recall@4"] == pytest.approx(1 / 3)  # only Q3 in the first 4
    assert final["chunk"]["mean"]["recall@4"] == pytest.approx(1 / 3)  # only Q1 after reranking
    lift = stage["reranker_lift"]["chunk"]["metrics"]["recall@4"]
    assert (lift["wins"], lift["ties"], lift["losses"]) == (1, 1, 1)  # Q1 won, Q2 not the reranker's fault, Q3 lost
    assert stage["reranker_efficiency"] == pytest.approx(0.5)


def test_runs_without_a_candidate_stage_are_unaffected():
    records = [{"id": "Q1", "contexts": ["A"], "context_doc_ids": ["a"], "retrieval_calls": [{"retrieval_stage": None, "results": []}]}]
    assert candidate_view(records) is None
    assert _candidate_stage(records, {}, set(), {}, (4,), 4) is None


def test_candidate_view_truncates_without_changing_the_record():
    record = {"id": "Q1", "retrieval_results": [{"chunk_id": "f#0"}], "retrieval_calls": [{"retrieval_stage": "candidate", "results": [{"chunk_id": f"c#{i}"} for i in range(6)]}]}
    (view,) = candidate_view([record], 4)
    assert ranked_chunk_ids(view, {})[0] == ["c#0", "c#1", "c#2", "c#3"]
    assert record["retrieval_results"] == [{"chunk_id": "f#0"}]
