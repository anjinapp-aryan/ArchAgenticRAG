"""Deterministic qrels from golden evidence quotes, and the committed qrels file."""

from __future__ import annotations

import json

from langchain_core.documents import Document

from archagenticrag.evaluation.dataset import GoldenDataset, file_sha256, load_dataset
from archagenticrag.evaluation.relevance import build_qrels, load_qrels, match_key, render_rst

from .conftest import GOLDEN_PATH, REPO_ROOT

QRELS_FILE = REPO_ROOT / "eval" / "datasets" / "peps-v1" / "qrels" / "peps_v1_bge_small_docling_480.json"


def test_quote_markup_is_rendered_like_the_corpus():
    assert render_rst("the notation ``NAME := expr``.").strip() == "the notation NAME := expr."
    assert render_rst("However, :pep:`484` only specifies").strip() == "However, PEP 484 only specifies"
    # a trailing "::" makes docutils warn; the warning must not leak into the text
    assert "WARNING" not in render_rst("using the following special import::")


def test_match_key_ignores_docling_spacing_emphasis_and_footnote_links():
    chunk = "write a project's core metadata [[1]](#footnote-1) in a pyproject.toml file, *no* checks ."
    assert match_key(render_rst("project's `core metadata`_ in a ``pyproject.toml`` file")) in match_key(chunk)
    assert match_key("*no* checks.") in match_key(chunk)
    assert match_key("checks") not in match_key("rechecks")  # whole tokens only


def _dataset(evidence: list[dict], source_documents: list[str]) -> GoldenDataset:
    return GoldenDataset.model_validate(
        {
            "dataset_id": "t",
            "version": "1",
            "corpus_id": "c",
            "created": "2026-10-27",
            "description": "t",
            "items": [
                {
                    "id": "Q1",
                    "category": "A_direct_factual",
                    "difficulty": "easy",
                    "expected_behavior": "answer",
                    "question": "q?",
                    "ground_truth": "a.",
                    "source_documents": source_documents,
                    "evidence": evidence,
                },
                {
                    "id": "E1",
                    "category": "E_out_of_corpus",
                    "difficulty": "easy",
                    "expected_behavior": "abstain",
                    "question": "q?",
                    "ground_truth": "not in corpus",
                    "source_documents": [],
                    "evidence": [],
                },
            ],
        }
    )


def _chunk(chunk_id: str, text: str) -> Document:
    return Document(page_content=text, metadata={"chunk_id": chunk_id, "doc_id": chunk_id.split("#")[0]})


def test_build_qrels_labels_only_chunks_of_the_cited_document():
    chunks = [
        _chunk("d1#000", "Intro. Use 4 spaces per indentation level."),
        _chunk("d1#001", "Other text."),
        _chunk("d2#000", "Copied: use 4 spaces per indentation level."),
    ]
    dataset = _dataset([{"doc_id": "d1", "quote": "Use 4 spaces per indentation level."}], ["d1"])
    qrels = build_qrels(dataset, chunks, {"collection": "c1"})
    q1 = qrels["queries"]["Q1"]
    assert q1["chunk_relevance"] == {"d1#000": 1}
    assert q1["doc_relevance"] == {"d1": 1}
    assert q1["evidence"][0]["also_found_in"] == ["d2#000"]
    assert "E1" not in qrels["queries"]  # abstain items have no relevant chunks
    assert qrels["unmatched_evidence"] == []
    assert qrels["chunk_set"]["chunks"] == 3 and len(qrels["chunk_catalog"]) == 3


def test_unmatched_evidence_is_reported_not_dropped():
    chunks = [_chunk("d1#000", "The quote starts here"), _chunk("d1#001", "and ends here.")]
    dataset = _dataset([{"doc_id": "d1", "quote": "The quote starts here and ends here."}], ["d1"])
    qrels = build_qrels(dataset, chunks, {"collection": "c1"})
    assert qrels["queries"]["Q1"]["chunk_relevance"] == {}
    assert [m["id"] for m in qrels["unmatched_evidence"]] == ["Q1"]


def test_committed_qrels_cover_every_evidence_quote_of_the_current_dataset():
    qrels = load_qrels(QRELS_FILE)
    dataset = load_dataset(GOLDEN_PATH)
    assert qrels["dataset"]["sha256"] == file_sha256(GOLDEN_PATH)
    assert qrels["unmatched_evidence"] == []
    with_evidence = {item.id for item in dataset.items if item.evidence}
    assert set(qrels["queries"]) == with_evidence
    for item in dataset.items:
        if item.evidence:
            labelled = qrels["queries"][item.id]
            assert len(labelled["evidence"]) == len(item.evidence)
            assert all(ev["chunks"] for ev in labelled["evidence"]), item.id
            assert set(labelled["chunk_relevance"]) <= set(qrels["chunk_catalog"])
    assert json.loads(QRELS_FILE.read_text(encoding="utf-8"))["chunk_set"]["collection"] == "peps_v1_bge_small_docling_480"
