"""Basic RAG graph: contract, wiring and evaluator compatibility (offline: fake LLM + in-memory Qdrant)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import BaseMessage

from archagenticrag.evaluation.config import TargetRef
from archagenticrag.evaluation.target import load_factory, run_target
from archagenticrag.graphs.basic_rag import SYSTEM_PROMPT, build_graph, format_documents
from archagenticrag.rag.settings import SettingsError, parse_settings
from archagenticrag.rag.vector_store import VectorStoreError, index_documents


class RecordingChatModel(FakeListChatModel):
    """Fake chat model that keeps the messages it was sent."""

    seen: list[list[BaseMessage]] = []

    def _call(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> str:
        self.seen.append(messages)
        return super()._call(messages, *args, **kwargs)


@pytest.fixture
def indexed(memory_client, system, fake_embeddings, sample_chunks):
    index_documents(memory_client, parse_settings(system), fake_embeddings, sample_chunks, {"corpus_id": "test"})
    return memory_client


def _graph(indexed, system, fake_embeddings, answer="79 characters."):
    llm = RecordingChatModel(responses=[answer], seen=[])
    return build_graph(system=system, client=indexed, embeddings=fake_embeddings, llm=llm), llm


def test_build_graph_is_the_configured_factory():
    assert load_factory(TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph")) is build_graph


def test_graph_is_exactly_retrieve_then_generate(indexed, system, fake_embeddings):
    graph, _ = _graph(indexed, system, fake_embeddings)
    shape = graph.get_graph()
    assert set(shape.nodes) == {"__start__", "retrieve", "generate", "__end__"}
    assert {(e.source, e.target) for e in shape.edges} == {
        ("__start__", "retrieve"),
        ("retrieve", "generate"),
        ("generate", "__end__"),
    }


def test_question_flows_through_retrieve_and_generate(indexed, system, fake_embeddings, sample_chunks):
    system["retrieval"]["top_k"] = 2
    graph, llm = _graph(indexed, system, fake_embeddings)
    out = graph.invoke({"question": "What is the maximum line length?"})
    assert out["answer"] == "79 characters."
    assert len(out["documents"]) == 2  # top_k respected
    assert out["context"] == format_documents(out["documents"])
    # The model saw the retrieved context and the question, nothing else.
    (messages,) = llm.seen
    assert messages[0].content == SYSTEM_PROMPT.format(context=out["context"])
    assert messages[1].content == "What is the maximum line length?"


def test_prompt_forbids_outside_knowledge_and_requires_admitting_gaps():
    assert "only" in SYSTEM_PROMPT and "do not invent" in SYSTEM_PROMPT.lower()
    assert "do not contain the answer" in SYSTEM_PROMPT


def test_format_documents_labels_sources():
    from langchain_core.documents import Document

    text = format_documents([Document(page_content="body", metadata={"doc_id": "pep-0008", "section": "Code Lay-out"})])
    assert text == "[1] (pep-0008 › Code Lay-out)\nbody"
    assert format_documents([]) == "(no passages retrieved)"


def test_eval_metadata_describes_the_index(indexed, system, fake_embeddings):
    graph, _ = _graph(indexed, system, fake_embeddings)
    assert graph.eval_metadata["graph"] == "basic_rag"
    assert graph.eval_metadata["index"]["embedding_dimension"] == 384


def test_invalid_system_fails_before_touching_qdrant(system):
    system["retrieval"]["top_k"] = -1
    with pytest.raises(SettingsError):
        build_graph(system=system, client=object(), embeddings=object(), llm=object())


def test_missing_index_fails_clearly(memory_client, system, fake_embeddings):
    with pytest.raises(VectorStoreError, match="ingest"):
        build_graph(system=system, client=memory_client, embeddings=fake_embeddings, llm=FakeListChatModel(responses=["x"]))


async def test_phase2_evaluator_can_run_the_graph(indexed, system, fake_embeddings):
    graph, _ = _graph(indexed, system, fake_embeddings)
    result = await run_target(graph, TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph"), "Max line length?")
    assert result.error is None
    assert result.answer == "79 characters."
    assert len(result.contexts) == 3
    assert set(result.context_doc_ids) == {"pep-0008", "pep-0020", "pep-0572"}
    assert result.llm_calls == 1
    assert result.retrieval_latency_s > 0 and result.generation_latency_s > 0
