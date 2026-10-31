"""Retrieval instrumentation: ranks, scores (only when exposed), latency, method."""

from __future__ import annotations

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda

from archagenticrag.evaluation.config import TargetRef
from archagenticrag.evaluation.retrieval_trace import RetrievalRecorder, describe_documents
from archagenticrag.evaluation.target import run_target

REF = TargetRef(factory="x.y:z")


def _doc(chunk_id: str, **extra) -> Document:
    return Document(page_content=chunk_id, metadata={"chunk_id": chunk_id, "doc_id": chunk_id.split("#")[0], **extra})


class StaticRetriever(BaseRetriever):
    docs: list[Document]

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return list(self.docs)


class Reranker(BaseRetriever):
    """Stands in for a reranking wrapper: calls a base retriever, reverses, adds relevance_score."""

    base: BaseRetriever

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        docs = self.base.invoke(query, config={"callbacks": run_manager.get_child()})
        return [_doc(d.metadata["chunk_id"], relevance_score=0.9 - 0.1 * i) for i, d in enumerate(reversed(docs))]


def test_rank_and_ids_are_captured_and_missing_score_is_none():
    results = describe_documents([_doc("pep-0008#001"), Document(page_content="x", metadata={"source": "a/pep-0020.rst"})])
    assert [r["rank"] for r in results] == [1, 2]
    assert results[0]["chunk_id"] == "pep-0008#001" and results[0]["doc_id"] == "pep-0008"
    assert results[1]["chunk_id"] is None and results[1]["doc_id"] == "pep-0020"
    assert all(r["score"] is None and r["score_key"] is None for r in results)


def test_exposed_score_is_captured():
    (hit,) = describe_documents([_doc("a#0", relevance_score=0.75)])
    assert hit["score"] == 0.75 and hit["score_key"] == "relevance_score"


def test_recorder_captures_every_call_with_latency_and_method():
    recorder = RetrievalRecorder()
    base = StaticRetriever(docs=[_doc("a#0"), _doc("b#0")])
    labelled = base.with_config(metadata={"retrieval_method": "dense"})
    labelled.invoke("q1", config={"callbacks": [recorder]})
    base.invoke("q2", config={"callbacks": [recorder]})
    first, second = recorder.calls
    assert first["query"] == "q1" and first["method"] == "dense"
    assert second["method"] == "StaticRetriever"
    assert first["latency_s"] >= 0 and first["error"] is None
    assert [r["chunk_id"] for r in first["results"]] == ["a#0", "b#0"]


def test_final_results_take_score_and_method_from_the_outer_retriever():
    recorder = RetrievalRecorder()
    reranker = Reranker(base=StaticRetriever(docs=[_doc("a#0"), _doc("b#0")])).with_config(metadata={"retrieval_method": "rerank"})
    docs = reranker.invoke("q", config={"callbacks": [recorder]})
    assert len(recorder.calls) == 2  # base call and reranker call
    final = recorder.final_results([Document(page_content=d.page_content, metadata={"chunk_id": d.metadata["chunk_id"], "doc_id": "x"}) for d in docs])
    assert [(r["rank"], r["chunk_id"], r["method"]) for r in final] == [(1, "b#0", "rerank"), (2, "a#0", "rerank")]
    assert final[0]["score"] == 0.9


async def test_run_target_records_final_ranking_and_calls():
    retriever = StaticRetriever(docs=[_doc("pep-0008#001"), _doc("pep-0020#000")])

    async def graph(inputs: dict, config=None) -> dict:
        docs = await retriever.ainvoke(inputs["question"], config=config)
        return {"answer": "79.", "documents": docs}

    res = await run_target(RunnableLambda(graph), REF, "max line length?")
    assert [(r["rank"], r["chunk_id"]) for r in res.retrieval_results] == [(1, "pep-0008#001"), (2, "pep-0020#000")]
    assert res.retrieval_results[0]["score"] is None
    assert len(res.retrieval_calls) == 1 and res.retrieval_calls[0]["query"] == "max line length?"
    assert res.retrieval_calls[0]["latency_s"] <= res.retrieval_latency_s + 1e-3


async def test_run_target_failure_records_no_ranking():
    def boom(inputs: dict) -> dict:
        raise RuntimeError("down")

    res = await run_target(RunnableLambda(boom), REF, "q")
    assert res.error and res.retrieval_results == [] and res.retrieval_calls == []
