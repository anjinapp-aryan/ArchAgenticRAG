from __future__ import annotations

import pytest

from archagenticrag.evaluation.analysis import Failure, retrieval_checks, summarize, triage
from archagenticrag.evaluation.config import Pricing, TriageThresholds
from archagenticrag.evaluation.dataset import load_dataset

from .conftest import GOLDEN_PATH

T = TriageThresholds()


def _item(item_id: str):
    return next(i for i in load_dataset(GOLDEN_PATH).items if i.id == item_id)


def _record(item_id="A01", error=None, doc_recall=1.0, **metric_values):
    item = _item(item_id)
    return {
        "id": item.id,
        "category": item.category.value,
        "error": error,
        "metrics": {k: {"value": v, "reason": None, "error": None} for k, v in metric_values.items()},
        "retrieval": {"source_doc_recall": doc_recall, "evidence_in_context": None},
        "latency_s": 1.0,
        "retrieval_latency_s": 0.1,
        "llm_calls": 1,
        "usage": {},
    }


GOOD = dict(context_recall=1.0, context_precision=1.0, faithfulness=1.0, answer_correctness=1.0, answer_relevancy=0.9)


def test_retrieval_checks_against_golden_evidence():
    item = _item("C01")  # sources: pep-0484, pep-0604
    contexts = ["... argument is common, there is a new special factory called ``Union``. ..."]
    checks = retrieval_checks(item, contexts, ["pep-0484", None])
    assert checks["source_doc_recall"] == 0.5
    assert checks["evidence_in_context"] == 0.5
    assert checks["retrieved_doc_ids"] == ["pep-0484"]


def test_retrieval_checks_unknown_when_target_gives_no_doc_ids():
    assert retrieval_checks(_item("A01"), ["text"], [None])["source_doc_recall"] is None


@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        (dict(GOOD), Failure.PASS),
        (dict(GOOD, doc_recall=0.0), Failure.RETRIEVAL_FAILURE),
        (dict(GOOD, context_recall=0.2), Failure.CONTEXT_FAILURE),
        (dict(GOOD, faithfulness=0.3), Failure.HALLUCINATION),
        (dict(GOOD, answer_correctness=0.1), Failure.GENERATION_FAILURE),
        (dict(GOOD, answer_relevancy=0.1), Failure.GENERATION_FAILURE),
        (dict(GOOD, error="TimeoutError: boom"), Failure.OTHER),
        ({k: v for k, v in GOOD.items() if k != "faithfulness"}, Failure.OTHER),  # cannot confirm pass
    ],
)
def test_triage_answerable_items(kwargs, label):
    assert triage(_item("A01"), _record(**kwargs), T)["label"] == label


def test_triage_blames_earliest_failing_stage():
    rec = _record(**dict(GOOD, context_recall=0.1, faithfulness=0.1))
    result = triage(_item("A01"), rec, T)
    assert result["label"] == Failure.CONTEXT_FAILURE
    assert "retrieval_too_narrow" in result["flags"]


def test_triage_flags_too_broad_retrieval():
    rec = _record(**dict(GOOD, context_precision=0.1))
    result = triage(_item("A01"), rec, T)
    assert result["label"] == Failure.PASS
    assert "retrieval_too_broad" in result["flags"]


@pytest.mark.parametrize(("value", "label"), [(1.0, Failure.PASS), (0.0, Failure.OUT_OF_CORPUS)])
def test_triage_out_of_corpus(value, label):
    assert triage(_item("E03"), _record("E03", abstention=value), T)["label"] == label


@pytest.mark.parametrize(("value", "label"), [(1.0, Failure.PASS), (0.0, Failure.AMBIGUITY)])
def test_triage_ambiguous(value, label):
    assert triage(_item("D01"), _record("D01", clarification=value), T)["label"] == label


def _summarized_records():
    records = []
    for item_id, kwargs in [
        ("A01", GOOD),
        ("A02", dict(GOOD, faithfulness=0.2)),
        ("E01", {"abstention": 0.0}),
        ("B01", dict(GOOD, context_recall=0.1)),
    ]:
        rec = _record(item_id, **kwargs)
        rec["triage"] = triage(_item(item_id), rec, T)
        records.append(rec)
    records[0]["usage"] = {"gen-model": {"input_tokens": 1_000_000, "output_tokens": 500_000}}
    records[1]["latency_s"] = 3.0
    return records


def test_summary_breaks_results_down_by_category():
    summary = summarize(_summarized_records(), pricing=[])
    assert summary["metrics_by_category"]["A_direct_factual"]["faithfulness"] == {"mean": pytest.approx(0.6), "n": 2}
    assert summary["pass_rate_by_category"]["A_direct_factual"] == 0.5
    assert summary["pass_rate_by_category"]["E_out_of_corpus"] == 0.0
    assert summary["failure_matrix"]["HALLUCINATION"]["count"] == 1
    assert sum(v["count"] for v in summary["failure_matrix"].values()) == 3
    assert summary["latency_s"]["p50"] == pytest.approx(1.0)
    assert summary["latency_s"]["p95"] == pytest.approx(2.7)


def test_cost_is_null_without_verified_pricing():
    summary = summarize(_summarized_records(), pricing=[])
    assert summary["tokens_by_model"]["gen-model"] == {"input_tokens": 1_000_000, "output_tokens": 500_000}
    assert summary["estimated_cost_usd_by_model"]["gen-model"] is None


def test_cost_uses_configured_pricing():
    price = Pricing(
        model="gen-model", input_usd_per_mtok=0.5, output_usd_per_mtok=2.0, source_url="https://x", verified_on="2026-10-01"
    )
    summary = summarize(_summarized_records(), pricing=[price])
    assert summary["estimated_cost_usd_by_model"]["gen-model"] == pytest.approx(1.5)
