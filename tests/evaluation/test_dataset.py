from __future__ import annotations

import copy
from collections import Counter

import pytest

from archagenticrag.evaluation.dataset import (
    Category,
    DatasetError,
    ExpectedBehavior,
    load_dataset,
    verify_traceability,
)

from .conftest import CORPUS_DIR, GOLDEN_PATH


def test_golden_dataset_loads_with_required_size_and_coverage():
    dataset = load_dataset(GOLDEN_PATH)
    assert 30 <= len(dataset.items) <= 50
    categories = Counter(item.category for item in dataset.items)
    assert set(categories) == set(Category), "every question category A-G must be covered"
    assert min(categories.values()) >= 5
    behaviors = {item.expected_behavior for item in dataset.items}
    assert behaviors == set(ExpectedBehavior)


def test_golden_dataset_is_traceable_to_corpus():
    assert verify_traceability(load_dataset(GOLDEN_PATH), CORPUS_DIR) == []


def test_out_of_corpus_items_cite_nothing_and_answerable_items_cite_evidence():
    for item in load_dataset(GOLDEN_PATH).items:
        if item.category is Category.E_OUT_OF_CORPUS:
            assert item.expected_behavior is ExpectedBehavior.ABSTAIN
        if item.expected_behavior is ExpectedBehavior.ANSWER:
            assert item.evidence


def test_multi_document_items_cite_at_least_two_documents():
    for item in load_dataset(GOLDEN_PATH).items:
        if item.category is Category.C_MULTI_DOCUMENT:
            assert len({e.doc_id for e in item.evidence}) >= 2, item.id


def _with_item_change(golden_raw: dict, index: int, **changes) -> dict:
    data = copy.deepcopy(golden_raw)
    for key, value in changes.items():
        if value is ...:
            data["items"][index].pop(key)
        else:
            data["items"][index][key] = value
    return data


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"ground_truth": ...}, "ground_truth"),  # missing ground truth
        ({"ground_truth": "   "}, "ground_truth"),  # blank ground truth
        ({"category": "Z_unknown"}, "category"),
        ({"difficulty": "trivial"}, "difficulty"),
        ({"evidence": []}, "evidence quote"),  # answerable without evidence
        ({"source_documents": []}, "source document"),
        ({"unexpected_field": 1}, "unexpected_field"),
    ],
)
def test_invalid_rows_are_rejected_with_their_id(golden_raw, write_json, changes, message):
    data = _with_item_change(golden_raw, 0, **changes)
    with pytest.raises(DatasetError) as err:
        load_dataset(write_json(data))
    assert "A01" in str(err.value)
    assert message in str(err.value)


def test_abstain_item_must_not_cite_evidence(golden_raw, write_json):
    index = next(i for i, row in enumerate(golden_raw["items"]) if row["expected_behavior"] == "abstain")
    data = _with_item_change(golden_raw, index, source_documents=["pep-0008"])
    with pytest.raises(DatasetError, match="abstain"):
        load_dataset(write_json(data))


def test_evidence_must_come_from_listed_source_documents(golden_raw, write_json):
    data = _with_item_change(golden_raw, 0, evidence=[{"doc_id": "pep-0484", "quote": "x"}])
    with pytest.raises(DatasetError, match="not in source_documents"):
        load_dataset(write_json(data))


def test_duplicate_ids_are_rejected(golden_raw, write_json):
    data = copy.deepcopy(golden_raw)
    data["items"][1]["id"] = data["items"][0]["id"]
    with pytest.raises(DatasetError, match="duplicate"):
        load_dataset(write_json(data))


def test_unreadable_dataset_raises_dataset_error(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetError):
        load_dataset(bad)
    with pytest.raises(DatasetError):
        load_dataset(tmp_path / "missing.json")


def test_invented_quote_is_detected(golden_raw, write_json):
    data = _with_item_change(
        golden_raw, 0, evidence=[{"doc_id": "pep-0008", "quote": "Limit all lines to a maximum of 80 characters."}]
    )
    problems = verify_traceability(load_dataset(write_json(data)), CORPUS_DIR)
    assert any("A01" in p and "quote not found" in p for p in problems)


def test_modified_corpus_file_is_detected(mini_repo):
    root, _ = mini_repo()
    corpus = root / "data" / "corpus" / "mini"
    (corpus / "doc-b.txt").write_text("tampered", encoding="utf-8")
    dataset = load_dataset(root / "eval" / "datasets" / "mini" / "golden.json")
    problems = verify_traceability(dataset, corpus)
    assert any("hash differs" in p for p in problems)
    assert any("quote not found" in p for p in problems)
