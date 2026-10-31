"""Retrieval ranking metrics (Recall@K, MRR, nDCG@K) over a run's recorded context lists.

The metric mathematics is ``ir_measures`` (Apache-2.0) on its default ``pytrec_eval`` backend,
i.e. the reference trec_eval implementation. This module only turns run records and qrels into
its input and back:

  * the ranked list of an item is the graph's final context list, in the order the generator
    saw it. Runs recorded before retrieval instrumentation are mapped back to chunk ids by the
    sha256 of each context text against the qrels' chunk catalog (exact match only);
  * a chunk appearing twice keeps its first (best) rank; contexts that map to no known chunk
    stay in the list as non-relevant placeholders, and are counted;
  * trec_eval ranks by score, so each list gets strictly decreasing synthetic scores from its
    rank order (similarity scores are not comparable across retrievers and are often absent);
  * every item with qrels counts in the mean; an item with an empty list scores 0.

Chunk-level metrics use the evidence-bearing chunks as relevant; document-level metrics use
``source_documents`` and are independent of the chunking.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from archagenticrag.evaluation.relevance import text_sha256

DEFAULT_CUTOFFS = (1, 3, 4, 5, 8, 10)  # 4 = baseline top_k, 8 = largest context list so far


def dedupe(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def ranked_chunk_ids(record: dict[str, Any], catalog_by_sha: dict[str, str]) -> tuple[list[str], int]:
    """Chunk ids in rank order and the number of contexts that map to no known chunk."""
    if record.get("retrieval_results"):
        ids = [hit.get("chunk_id") for hit in record["retrieval_results"]]
    else:
        ids = [catalog_by_sha.get(text_sha256(text)) for text in record.get("contexts") or []]
    unmapped = sum(1 for i in ids if not i)
    return dedupe([i or f"__unmapped_{n}" for n, i in enumerate(ids)]), unmapped


def ranked_doc_ids(record: dict[str, Any]) -> list[str]:
    ids = [hit.get("doc_id") for hit in record["retrieval_results"]] if record.get("retrieval_results") else record.get("context_doc_ids") or []
    return dedupe([i or f"__unknown_{n}" for n, i in enumerate(ids)])


def measure_names(cutoffs: tuple[int, ...]) -> list[str]:
    return [*(f"recall@{k}" for k in cutoffs), "mrr", *(f"ndcg@{k}" for k in cutoffs)]


def evaluate(qrels: dict[str, dict[str, int]], ranked: dict[str, list[str]], cutoffs: tuple[int, ...] = DEFAULT_CUTOFFS) -> dict[str, Any]:
    """Per-query and mean Recall@K / MRR / nDCG@K for every query in ``qrels``."""
    import ir_measures
    from ir_measures import RR, R, nDCG

    measures = {**{R @ k: f"recall@{k}" for k in cutoffs}, RR: "mrr", **{nDCG @ k: f"ndcg@{k}" for k in cutoffs}}
    run = {qid: {doc: float(len(ids) - i) for i, doc in enumerate(ids)} for qid, ids in ranked.items() if qid in qrels and ids}
    per_query: dict[str, dict[str, float]] = {qid: {name: 0.0 for name in measures.values()} for qid in qrels}
    if run:
        for m in ir_measures.iter_calc(list(measures), qrels, run):
            per_query[m.query_id][measures[m.measure]] = float(m.value)
    mean = {name: statistics.fmean(q[name] for q in per_query.values()) if per_query else None for name in measures.values()}
    return {"n": len(per_query), "mean": mean, "per_query": per_query}


def run_ranking(
    records: list[dict[str, Any]],
    qrels_data: dict[str, Any],
    cutoffs: tuple[int, ...] = DEFAULT_CUTOFFS,
    behaviors: tuple[str, ...] = ("answer",),
    only: set[str] | None = None,
) -> dict[str, Any]:
    """Chunk- and document-level ranking metrics for one run.

    Items with a system error count as empty lists (the system retrieved nothing usable).
    Only items whose expected behaviour is in ``behaviors`` (and, if given, whose id is in
    ``only``, e.g. the items every compared run completed) enter the means.
    """
    queries = {
        qid: q
        for qid, q in qrels_data["queries"].items()
        if q["expected_behavior"] in behaviors and (only is None or qid in only)
    }
    catalog_by_sha = {entry["sha256"]: cid for cid, entry in qrels_data["chunk_catalog"].items()}
    by_id = {r["id"]: r for r in records}

    chunk_ranked: dict[str, list[str]] = {}
    doc_ranked: dict[str, list[str]] = {}
    unmapped = 0
    for qid in queries:
        record = by_id.get(qid)
        if record is None or record.get("error"):
            chunk_ranked[qid], doc_ranked[qid] = [], []
            continue
        chunk_ranked[qid], missing = ranked_chunk_ids(record, catalog_by_sha)
        doc_ranked[qid] = ranked_doc_ids(record)
        unmapped += missing

    chunk = evaluate({qid: q["chunk_relevance"] for qid, q in queries.items()}, chunk_ranked, cutoffs)
    doc = evaluate({qid: q["doc_relevance"] for qid, q in queries.items()}, doc_ranked, cutoffs)

    groups: dict[str, list[str]] = defaultdict(list)
    for qid, q in queries.items():
        groups[q["category"]].append(qid)

    def by_category(level: dict[str, Any]) -> dict[str, dict[str, float]]:
        return {
            category: {
                "n": len(qids),
                **{name: statistics.fmean(level["per_query"][qid][name] for qid in qids) for name in measure_names(cutoffs)},
            }
            for category, qids in sorted(groups.items())
        }

    return {
        "behaviors": list(behaviors),
        "cutoffs": list(cutoffs),
        "items_missing_from_run": sorted(set(queries) - set(by_id)),
        "items_with_system_error": sorted(qid for qid in queries if (by_id.get(qid) or {}).get("error")),
        "unmapped_contexts": unmapped,
        "chunk": chunk,
        "doc": doc,
        "chunk_by_category": by_category(chunk),
        "doc_by_category": by_category(doc),
    }
