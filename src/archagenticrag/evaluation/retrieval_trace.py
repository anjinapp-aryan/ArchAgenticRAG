"""Per-item retrieval instrumentation, recorded through LangChain retriever callbacks.

Works for any graph without changing it: every retriever call (dense, sparse, hybrid,
a reranking wrapper, one call per rewritten or decomposed query, a CRAG retry...) is
captured with its query, latency and ranked results. The final ranked list is the
graph's context output, described by ``describe_documents``.

Scores are recorded only when the retriever exposes one in the document metadata (for
example ``relevance_score`` from LangChain document compressors / rerankers). Plain
``VectorStoreRetriever`` similarity search does not, so ``score`` is ``None`` there:
nothing is estimated. ``method`` is the retriever's own ``retrieval_method`` metadata
when an experiment sets it (``retriever.with_config(metadata={"retrieval_method": "hybrid"})``),
otherwise the retriever class and vector store LangChain reports.
"""

from __future__ import annotations

import time
from pathlib import PurePath
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

SCORE_KEYS = ("relevance_score", "score")


def doc_id_of(metadata: dict) -> str | None:
    for key in ("doc_id", "source", "file_path"):
        if metadata.get(key):
            return PurePath(str(metadata[key])).stem  # "data/corpus/peps/pep-0484.rst" -> "pep-0484"
    return None


def _score(metadata: dict) -> tuple[float | None, str | None]:
    for key in SCORE_KEYS:
        value = metadata.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), key
    return None, None


def describe_documents(documents: list[Any], method: str | None = None) -> list[dict[str, Any]]:
    """Ranked description of a document list: rank (1-based), ids, score if exposed, method."""
    results = []
    for rank, doc in enumerate(documents or [], start=1):
        metadata = getattr(doc, "metadata", None) or {}
        score, score_key = _score(metadata)
        results.append(
            {
                "rank": rank,
                "doc_id": doc_id_of(metadata),
                "chunk_id": metadata.get("chunk_id"),
                "score": score,
                "score_key": score_key,
                "method": method,
            }
        )
    return results


def _method(name: str | None, metadata: dict | None) -> str:
    metadata = metadata or {}
    if metadata.get("retrieval_method"):
        return str(metadata["retrieval_method"])
    store = metadata.get("ls_vector_store_provider")
    return f"{name or 'retriever'}({store})" if store else (name or "retriever")


class RetrievalRecorder(BaseCallbackHandler):
    """Collects every retriever call made while one item runs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._open: dict[Any, dict[str, Any]] = {}

    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None, metadata=None, name=None, **kwargs):  # noqa: ANN001
        self._open[run_id] = {
            "query": query,
            "method": _method(name, metadata),
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "run_id": str(run_id),
            "_start": time.perf_counter(),
        }

    def _close(self, run_id, documents, error) -> None:  # noqa: ANN001
        call = self._open.pop(run_id, None)
        if call is None:
            return
        call["latency_s"] = time.perf_counter() - call.pop("_start")
        call["results"] = describe_documents(documents, call["method"])
        call["error"] = error
        self.calls.append(call)

    def on_retriever_end(self, documents, *, run_id, **kwargs):  # noqa: ANN001
        self._close(run_id, documents, None)

    def on_retriever_error(self, error, *, run_id, **kwargs):  # noqa: ANN001
        self._close(run_id, [], f"{type(error).__name__}: {error}")

    def final_results(self, documents: list[Any]) -> list[dict[str, Any]]:
        """Describe the graph's final context list; method/score come from the call that returned the chunk."""
        by_chunk: dict[str, dict[str, Any]] = {}
        for call in self.calls:  # later calls (e.g. a reranker wrapping a base retriever) win
            for hit in call["results"]:
                if hit["chunk_id"]:
                    by_chunk[hit["chunk_id"]] = hit
        results = describe_documents(documents)
        for hit in results:
            source = by_chunk.get(hit["chunk_id"]) if hit["chunk_id"] else None
            if source:
                hit["method"] = source["method"]
                if hit["score"] is None and source["score"] is not None:
                    hit["score"], hit["score_key"] = source["score"], source["score_key"]
        return results
