from __future__ import annotations

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda

from archagenticrag.evaluation.config import TargetRef
from archagenticrag.evaluation.target import TargetError, load_factory, run_target

REF = TargetRef(factory="x.y:z")


class FakeRetriever(BaseRetriever):
    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return [
            Document(page_content="Limit all lines to a maximum of 79 characters.", metadata={"source": "data/corpus/peps/pep-0008.rst"}),
            Document(page_content="Beautiful is better than ugly.", metadata={"doc_id": "pep-0020"}),
        ]


def _basic_rag():
    """A real LangChain pipeline (retriever -> chat model) with fake components."""
    retriever = FakeRetriever()
    llm = FakeListChatModel(responses=["79 characters."])

    async def run(inputs: dict, config=None) -> dict:
        docs = await retriever.ainvoke(inputs["question"], config=config)
        answer = await llm.ainvoke(inputs["question"], config=config)
        return {"answer": answer.content, "documents": docs}

    return RunnableLambda(run)


async def test_run_target_captures_answer_contexts_doc_ids_and_call_stats():
    result = await run_target(_basic_rag(), REF, "Max line length?")
    assert result.error is None
    assert result.answer == "79 characters."
    assert result.contexts[0].startswith("Limit all lines")
    assert result.context_doc_ids == ["pep-0008", "pep-0020"]
    assert result.llm_calls == 1
    assert result.latency_s >= result.retrieval_latency_s > 0


async def test_plain_string_contexts_are_accepted():
    target = RunnableLambda(lambda inputs: {"answer": "a", "documents": ["ctx one", "ctx two"]})
    result = await run_target(target, REF, "q")
    assert result.contexts == ["ctx one", "ctx two"]
    assert result.context_doc_ids == [None, None]


async def test_target_exception_is_returned_not_raised():
    def boom(inputs):
        raise ConnectionError("qdrant down")

    result = await run_target(RunnableLambda(boom), REF, "q")
    assert result.error == "ConnectionError: qdrant down"
    assert result.answer == "" and result.contexts == []


async def test_missing_answer_key_is_an_error():
    result = await run_target(RunnableLambda(lambda inputs: {"documents": []}), REF, "q")
    assert "KeyError" in result.error


def test_missing_target_module_gives_clear_error():
    with pytest.raises(TargetError, match="cannot import target module 'archagenticrag.graphs.no_such_graph'"):
        load_factory(TargetRef(factory="archagenticrag.graphs.no_such_graph:build_graph"))


def test_missing_target_function_gives_clear_error():
    with pytest.raises(TargetError, match="has no attribute 'nope'"):
        load_factory(TargetRef(factory="archagenticrag.graphs.basic_rag:nope"))
