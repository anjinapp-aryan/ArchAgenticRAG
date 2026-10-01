"""Per-item diagnostics, failure triage and run summaries.

Quality scores come from Ragas. This module only:
  * computes two deterministic retrieval checks against the golden evidence
    (was the right document retrieved, does the retrieved text contain the evidence),
  * maps metric scores to a provisional failure label (a rubric, not a metric),
  * aggregates per-category statistics, latency and tokens.
Labels are a starting point for human review, not ground truth.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from enum import StrEnum
from typing import Any

from archagenticrag.evaluation.config import Pricing, TriageThresholds
from archagenticrag.evaluation.dataset import ExpectedBehavior, GoldenItem


class Failure(StrEnum):
    PASS = "PASS"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"  # none of the source documents retrieved
    CONTEXT_FAILURE = "CONTEXT_FAILURE"  # right document(s), but retrieved text insufficient
    HALLUCINATION = "HALLUCINATION"  # context sufficient, answer not grounded in it
    GENERATION_FAILURE = "GENERATION_FAILURE"  # context sufficient and grounded, answer wrong/off-target
    AMBIGUITY = "AMBIGUITY"  # ambiguous question answered as if it had one meaning
    OUT_OF_CORPUS = "OUT_OF_CORPUS"  # answered a question the corpus cannot answer
    OTHER = "OTHER"  # system error, metric error, or not classifiable


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def retrieval_checks(item: GoldenItem, contexts: list[str], context_doc_ids: list[str | None]) -> dict[str, Any]:
    known_ids = {d for d in context_doc_ids if d}
    doc_recall = None
    if item.source_documents and known_ids:
        doc_recall = len(set(item.source_documents) & known_ids) / len(set(item.source_documents))
    evidence_hit = None
    if item.evidence:
        joined = _norm(" ".join(contexts))
        evidence_hit = sum(_norm(e.quote) in joined for e in item.evidence) / len(item.evidence)
    return {
        "source_doc_recall": doc_recall,
        "evidence_in_context": evidence_hit,
        "retrieved_doc_ids": sorted(known_ids),
    }


def _value(metrics: dict[str, dict], name: str) -> float | None:
    return (metrics.get(name) or {}).get("value")


def triage(item: GoldenItem, record: dict[str, Any], t: TriageThresholds) -> dict[str, Any]:
    """Assign one primary failure label plus secondary flags to a scored item."""
    metrics = record["metrics"]
    checks = record["retrieval"]
    flags: list[str] = []
    reasons: list[str] = []

    def result(label: Failure) -> dict[str, Any]:
        return {"label": label.value, "flags": flags, "reasons": reasons}

    if record.get("error"):
        reasons.append(f"system error: {record['error']}")
        return result(Failure.OTHER)

    metric_errors = [n for n, m in metrics.items() if m.get("error")]
    if metric_errors:
        flags.append("metric_error:" + ",".join(metric_errors))

    if item.expected_behavior is ExpectedBehavior.ABSTAIN:
        abstained = _value(metrics, "abstention")
        if abstained is None:
            return result(Failure.OTHER)
        return result(Failure.PASS if abstained == 1.0 else Failure.OUT_OF_CORPUS)

    if item.expected_behavior is ExpectedBehavior.CLARIFY:
        handled = _value(metrics, "clarification")
        if handled is None:
            return result(Failure.OTHER)
        return result(Failure.PASS if handled == 1.0 else Failure.AMBIGUITY)

    # Answerable items: walk the pipeline from retrieval to generation and blame the first stage that fails.
    recall = _value(metrics, "context_recall")
    precision = _value(metrics, "context_precision")
    faithfulness = _value(metrics, "faithfulness")
    correctness = _value(metrics, "answer_correctness")
    relevancy = _value(metrics, "answer_relevancy")

    if precision is not None and precision < t.context_precision and recall is not None and recall >= t.context_recall:
        flags.append("retrieval_too_broad")  # needed info present but buried in noise

    if checks["source_doc_recall"] == 0.0:
        reasons.append("no source document among retrieved chunks")
        return result(Failure.RETRIEVAL_FAILURE)
    if recall is not None and recall < t.context_recall:
        flags.append("retrieval_too_narrow")
        reasons.append(f"context_recall {recall:.2f} < {t.context_recall}")
        return result(Failure.CONTEXT_FAILURE)
    if faithfulness is not None and faithfulness < t.faithfulness:
        reasons.append(f"faithfulness {faithfulness:.2f} < {t.faithfulness}")
        return result(Failure.HALLUCINATION)
    if correctness is not None and correctness < t.answer_correctness:
        reasons.append(f"answer_correctness {correctness:.2f} < {t.answer_correctness}")
        return result(Failure.GENERATION_FAILURE)
    if relevancy is not None and relevancy < t.answer_relevancy:
        reasons.append(f"answer_relevancy {relevancy:.2f} < {t.answer_relevancy}")
        return result(Failure.GENERATION_FAILURE)
    if None in (recall, faithfulness, correctness):
        reasons.append("missing metric values; cannot confirm pass")
        return result(Failure.OTHER)
    return result(Failure.PASS)


def _percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[pct - 1]


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize(records: list[dict[str, Any]], pricing: list[Pricing]) -> dict[str, Any]:
    by_category: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    overall: dict[str, list[float]] = defaultdict(list)
    metric_errors: Counter[str] = Counter()
    for r in records:
        for name, m in r["metrics"].items():
            if m.get("value") is None:
                metric_errors[name] += 1
                continue
            by_category[r["category"]][name].append(m["value"])
            overall[name].append(m["value"])

    labels = Counter(r["triage"]["label"] for r in records)
    failures = {k: v for k, v in labels.items() if k != Failure.PASS.value}
    n_failed = sum(failures.values())

    latencies = [r["latency_s"] for r in records if not r.get("error")]
    retrieval = [r["retrieval_latency_s"] for r in records if not r.get("error")]
    generation = [r.get("generation_latency_s", 0.0) for r in records if not r.get("error")]
    tokens: dict[str, dict[str, int]] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0})
    for r in records:
        for model, usage in (r.get("usage") or {}).items():
            tokens[model]["input_tokens"] += usage.get("input_tokens", 0)
            tokens[model]["output_tokens"] += usage.get("output_tokens", 0)

    prices = {p.model: p for p in pricing}
    cost: dict[str, Any] = {}
    for model, tok in tokens.items():
        p = prices.get(model)
        cost[model] = (
            None  # unknown price: never guessed
            if p is None
            else round(tok["input_tokens"] / 1e6 * p.input_usd_per_mtok + tok["output_tokens"] / 1e6 * p.output_usd_per_mtok, 6)
        )

    return {
        "items": len(records),
        "system_errors": sum(1 for r in records if r.get("error")),
        "metric_value_missing": dict(metric_errors),
        "metrics_overall": {k: {"mean": _mean(v), "n": len(v)} for k, v in sorted(overall.items())},
        "metrics_by_category": {
            cat: {k: {"mean": _mean(v), "n": len(v)} for k, v in sorted(ms.items())}
            for cat, ms in sorted(by_category.items())
        },
        "pass_rate_by_category": {
            cat: sum(r["triage"]["label"] == "PASS" for r in records if r["category"] == cat)
            / sum(r["category"] == cat for r in records)
            for cat in sorted({r["category"] for r in records})
        },
        "failure_matrix": {
            k: {"count": v, "pct_of_failures": v / n_failed if n_failed else 0.0} for k, v in sorted(failures.items())
        },
        "latency_s": {
            "mean": _mean(latencies),
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "retrieval_mean": _mean(retrieval),
            "retrieval_p50": _percentile(retrieval, 50),
            "retrieval_p95": _percentile(retrieval, 95),
            "generation_mean": _mean(generation),
            "generation_p50": _percentile(generation, 50),
            "generation_p95": _percentile(generation, 95),
        },
        "llm_calls": {"total": sum(r["llm_calls"] for r in records), "mean_per_item": _mean([r["llm_calls"] for r in records])},
        "tokens_by_model": dict(tokens),
        "estimated_cost_usd_by_model": cost,
    }
