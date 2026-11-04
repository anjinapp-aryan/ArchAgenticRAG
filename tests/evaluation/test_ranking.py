"""Ranking metrics (ir_measures / trec_eval) over recorded context lists. Hand-computed expectations."""

from __future__ import annotations

import math

import pytest

from archagenticrag.evaluation.ranking import dedupe, evaluate, ranked_chunk_ids, ranked_doc_ids, run_ranking
from archagenticrag.evaluation.relevance import text_sha256

CUTS = (1, 3, 5)


def test_recall_mrr_ndcg_single_relevant():
    out = evaluate({"q": {"b": 1}}, {"q": ["a", "b", "c"]}, CUTS)["per_query"]["q"]
    assert out["recall@1"] == 0.0 and out["recall@3"] == 1.0 and out["recall@5"] == 1.0
    assert out["mrr"] == pytest.approx(0.5)
    assert out["ndcg@3"] == pytest.approx(1 / math.log2(3))  # gain 1 at rank 2, ideal at rank 1


def test_multiple_relevant():
    out = evaluate({"q": {"a": 1, "c": 1, "z": 1}}, {"q": ["a", "b", "c"]}, CUTS)["per_query"]["q"]
    assert out["recall@1"] == pytest.approx(1 / 3)
    assert out["recall@3"] == pytest.approx(2 / 3)
    assert out["mrr"] == 1.0
    dcg = 1 + 1 / math.log2(4)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert out["ndcg@3"] == pytest.approx(dcg / idcg)


def test_no_relevant_result_and_empty_list_score_zero():
    result = evaluate({"q1": {"x": 1}, "q2": {"y": 1}}, {"q1": ["a", "b"], "q2": []}, CUTS)
    for qid in ("q1", "q2"):
        assert all(v == 0.0 for v in result["per_query"][qid].values())
    assert result["n"] == 2 and result["mean"]["mrr"] == 0.0


def test_query_missing_from_run_counts_as_zero_in_the_mean():
    result = evaluate({"q1": {"a": 1}, "q2": {"b": 1}}, {"q1": ["a"]}, CUTS)
    assert result["mean"]["recall@1"] == 0.5


def test_duplicates_keep_their_first_rank():
    assert dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
    record = {"retrieval_results": [{"chunk_id": "x"}, {"chunk_id": "x"}, {"chunk_id": "rel"}]}
    ids, _ = ranked_chunk_ids(record, {})
    assert ids == ["x", "rel"]
    assert evaluate({"q": {"rel": 1}}, {"q": ids}, CUTS)["per_query"]["q"]["mrr"] == 0.5


def test_old_runs_map_contexts_to_chunks_by_text_hash():
    catalog = {text_sha256("alpha"): "doc-a#000", text_sha256("beta"): "doc-b#000"}
    ids, unmapped = ranked_chunk_ids({"contexts": ["beta", "unknown text", "alpha"]}, catalog)
    assert ids == ["doc-b#000", "__unmapped_1", "doc-a#000"] and unmapped == 1


def test_doc_ranking_uses_context_doc_ids_and_dedupes():
    assert ranked_doc_ids({"context_doc_ids": ["d1", "d1", None, "d2"]}) == ["d1", "__unknown_2", "d2"]


QRELS = {
    "chunk_catalog": {"a#0": {"doc_id": "a", "sha256": text_sha256("A0")}, "b#0": {"doc_id": "b", "sha256": text_sha256("B0")}},
    "queries": {
        "Q1": {"category": "A", "expected_behavior": "answer", "chunk_relevance": {"a#0": 1}, "doc_relevance": {"a": 1}},
        "Q2": {"category": "B", "expected_behavior": "answer", "chunk_relevance": {"b#0": 1}, "doc_relevance": {"b": 1}},
        "Q3": {"category": "D", "expected_behavior": "clarify", "chunk_relevance": {"a#0": 1}, "doc_relevance": {"a": 1}},
    },
}


def test_run_ranking_counts_system_errors_as_empty_and_filters_behaviour():
    records = [
        {"id": "Q1", "contexts": ["B0", "A0"], "context_doc_ids": ["b", "a"]},
        {"id": "Q2", "error": "RateLimitError", "contexts": []},
        {"id": "Q3", "contexts": ["A0"], "context_doc_ids": ["a"]},
    ]
    out = run_ranking(records, QRELS, CUTS)
    assert out["chunk"]["n"] == 2  # Q3 (clarify) not in the default answerable set
    assert out["chunk"]["mean"]["mrr"] == pytest.approx(0.25)  # Q1: 0.5, Q2: 0
    assert out["items_with_system_error"] == ["Q2"]
    assert out["doc"]["mean"]["recall@3"] == 0.5
    paired = run_ranking(records, QRELS, CUTS, only={"Q1"})
    assert paired["chunk"]["n"] == 1 and paired["chunk"]["mean"]["mrr"] == 0.5
    assert out["chunk_by_category"]["A"]["n"] == 1
