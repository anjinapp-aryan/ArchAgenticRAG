"""Phase 3.1 decomposition graph (docs/PHASE-3.1-DESIGN.md, section 13). Offline: fake LLM + in-memory Qdrant."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from archagenticrag.evaluation.config import TargetRef, load_config
from archagenticrag.evaluation.target import load_factory, run_target
from archagenticrag.graphs import basic_rag
from archagenticrag.graphs.decompose_rag import (
    SubQuestions,
    build_graph,
    merge_hits,
    normalize_sub_questions,
)
from archagenticrag.rag.settings import SettingsError, parse_settings
from archagenticrag.rag.vector_store import index_documents

from ..rag.conftest import REPO_ROOT
from .test_basic_rag import RecordingChatModel

QUESTION = "What is the maximum line length?"


class FakeDecomposerLLM(RecordingChatModel):
    """Answers like RecordingChatModel; ``with_structured_output`` returns scripted sub-questions."""

    proposals: list[str] = []
    fail: bool = False
    decompose_calls: list[Any] = []

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ANN003
        assert schema is SubQuestions

        def run(prompt_value):  # noqa: ANN001
            self.decompose_calls.append(prompt_value)
            if self.fail:
                raise ValueError("decomposer returned invalid JSON")
            return SubQuestions(sub_questions=list(self.proposals))

        return RunnableLambda(run)


class RetrieverQueries(BaseCallbackHandler):
    def __init__(self) -> None:
        self.queries: list[str] = []

    def on_retriever_start(self, serialized, query, **kwargs):  # noqa: ANN001, ANN003
        self.queries.append(query)


@pytest.fixture
def decomposition_system(system) -> dict:
    import copy

    phase31 = copy.deepcopy(system)  # leave the baseline `system` fixture untouched
    phase31["decomposition"] = {"max_sub_questions": 3, "max_context_chunks": 8}
    return phase31


@pytest.fixture
def indexed(memory_client, system, fake_embeddings, sample_chunks):
    index_documents(memory_client, parse_settings(system), fake_embeddings, sample_chunks, {"corpus_id": "test"})
    return memory_client


def _graph(indexed, system, fake_embeddings, proposals=(), fail=False):
    llm = FakeDecomposerLLM(responses=["79 characters."], seen=[], proposals=list(proposals), fail=fail, decompose_calls=[])
    return build_graph(system=system, client=indexed, embeddings=fake_embeddings, llm=llm), llm


def test_graph_shape_is_decompose_fanout_merge_generate(indexed, decomposition_system, fake_embeddings):
    graph, _ = _graph(indexed, decomposition_system, fake_embeddings)
    shape = graph.get_graph()
    assert set(shape.nodes) == {"__start__", "decompose", "retrieve_one", "merge", "generate", "__end__"}
    assert {(e.source, e.target) for e in shape.edges} == {
        ("__start__", "decompose"),
        ("decompose", "retrieve_one"),
        ("retrieve_one", "merge"),
        ("merge", "generate"),
        ("generate", "__end__"),
    }
    assert load_factory(TargetRef(factory="archagenticrag.graphs.decompose_rag:build_graph")) is build_graph


# 1. single-need question -> exactly the baseline retrieval
def test_single_need_question_reproduces_baseline_retrieval(indexed, system, decomposition_system, fake_embeddings):
    graph, _ = _graph(indexed, decomposition_system, fake_embeddings, proposals=[])
    out = graph.invoke({"question": QUESTION})
    assert out["sub_questions"] == [QUESTION]

    base_llm = RecordingChatModel(responses=["79 characters."], seen=[])
    base = basic_rag.build_graph(system=system, client=indexed, embeddings=fake_embeddings, llm=base_llm)
    expected = base.invoke({"question": QUESTION})
    assert [d.metadata["chunk_id"] for d in out["documents"]] == [d.metadata["chunk_id"] for d in expected["documents"]]
    assert out["context"] == expected["context"]


# 2. cap at 3, original first, blank/duplicate proposals dropped
def test_normalize_sub_questions():
    proposals = ["", "  What is PEP 8? ", "what is   pep 8?", "What is PEP 20?", "What is PEP 572?", QUESTION.upper()]
    assert normalize_sub_questions(QUESTION, proposals, 3) == [QUESTION, "What is PEP 8?", "What is PEP 20?"]
    assert normalize_sub_questions(QUESTION, proposals, 1) == [QUESTION]


def test_decomposer_output_is_capped_in_the_graph(indexed, decomposition_system, fake_embeddings):
    graph, _ = _graph(indexed, decomposition_system, fake_embeddings, proposals=["a?", "b?", "c?", "d?"])
    out = graph.invoke({"question": QUESTION})
    assert out["sub_questions"] == [QUESTION, "a?", "b?"]


# 3. one retrieval per sub-question (Send fan-out)
def test_fan_out_runs_one_retrieval_per_sub_question(indexed, decomposition_system, fake_embeddings):
    graph, _ = _graph(indexed, decomposition_system, fake_embeddings, proposals=["What is PEP 20?", "What is PEP 572?"])
    handler = RetrieverQueries()
    out = graph.invoke({"question": QUESTION}, config={"callbacks": [handler]})
    assert sorted(handler.queries) == sorted(out["sub_questions"])
    assert len(out["retrieved"]) == 3


# 4. merge: unique by chunk_id, original first, round-robin, capped
def _doc(chunk_id: str) -> Document:
    return Document(page_content=chunk_id, metadata={"chunk_id": chunk_id, "doc_id": chunk_id.split("#")[0]})


def test_merge_hits_dedups_orders_and_caps():
    hits = [
        {"sub_question_index": 2, "documents": [_doc("c#1"), _doc("a#1")]},
        {"sub_question_index": 0, "documents": [_doc("a#1"), _doc("a#2")]},
        {"sub_question_index": 1, "documents": [_doc("b#1"), _doc("b#2"), _doc("b#3")]},
    ]
    merged = [d.metadata["chunk_id"] for d in merge_hits(hits, max_chunks=8)]
    assert merged == ["a#1", "a#2", "b#1", "c#1", "b#2", "b#3"]
    assert [d.metadata["chunk_id"] for d in merge_hits(hits, max_chunks=3)] == ["a#1", "a#2", "b#1"]


# 5. generate node and prompt are the Basic RAG ones
def test_generate_uses_the_unchanged_basic_rag_prompt(indexed, decomposition_system, fake_embeddings):
    graph, llm = _graph(indexed, decomposition_system, fake_embeddings, proposals=["What is PEP 20?"])
    out = graph.invoke({"question": QUESTION})
    (messages,) = llm.seen  # exactly one generation call
    assert messages[0].content == basic_rag.SYSTEM_PROMPT.format(context=out["context"])
    assert messages[1].content == QUESTION
    assert out["answer"] == "79 characters."
    assert graph.eval_metadata["prompt"] == basic_rag.SYSTEM_PROMPT


# 6. evaluator contract, plus recorded sub-questions
async def test_evaluator_contract_and_recorded_sub_questions(indexed, decomposition_system, fake_embeddings):
    graph, _ = _graph(indexed, decomposition_system, fake_embeddings, proposals=["What is PEP 20?"])
    ref = TargetRef(factory="archagenticrag.graphs.decompose_rag:build_graph", record_keys=["sub_questions"])
    res = await run_target(graph, ref, QUESTION)
    assert res.error is None and res.answer == "79 characters."
    assert res.contexts and all(doc_id and doc_id.startswith("pep-") for doc_id in res.context_doc_ids)
    assert res.recorded == {"sub_questions": [QUESTION, "What is PEP 20?"]}


# 7. settings
def test_decomposition_settings_validation(decomposition_system):
    for bad in ({"max_sub_questions": 0}, {"max_sub_questions": 4}, {"max_context_chunks": 0}, {"extra": 1}):
        decomposition_system["decomposition"] = bad
        with pytest.raises(SettingsError):
            parse_settings(decomposition_system)


def test_retrieval_search_type_settings(system):
    assert parse_settings(system).retrieval.search_kwargs() == {"k": 4}  # baseline: similarity, k only
    assert parse_settings(system).retrieval.search_type == "similarity"
    system["retrieval"].update(search_type="mmr", fetch_k=20)
    assert parse_settings(system).retrieval.search_kwargs() == {"k": 4, "fetch_k": 20}
    system["retrieval"].update(fetch_k=2)  # fetch_k < top_k
    with pytest.raises(SettingsError):
        parse_settings(system)
    system["retrieval"].pop("fetch_k")
    with pytest.raises(SettingsError):
        parse_settings(system)  # mmr without fetch_k
    system["retrieval"].update(search_type="similarity", fetch_k=20)
    with pytest.raises(SettingsError):
        parse_settings(system)  # fetch_k without mmr


def test_graphs_refuse_the_other_phase_config(indexed, system, decomposition_system, fake_embeddings):
    llm = RecordingChatModel(responses=["x"], seen=[])
    with pytest.raises(SettingsError, match="decompose_rag"):
        basic_rag.build_graph(system=decomposition_system, client=indexed, embeddings=fake_embeddings, llm=llm)
    with pytest.raises(SettingsError, match="decomposition is required"):
        build_graph(system=system, client=indexed, embeddings=fake_embeddings, llm=llm)


def test_baseline_config_fingerprint_is_unchanged():
    # The Phase 2 baseline run was recorded with this fingerprint; new optional fields must not change it.
    assert load_config(REPO_ROOT / "eval/configs/baseline-basic-rag.yaml").fingerprint() == "63bf3b5f990cc9e5"


def test_phase_configs_differ_from_baseline_only_where_documented():
    import yaml

    def load(name):
        return yaml.safe_load((REPO_ROOT / "eval/configs" / name).read_text(encoding="utf-8"))

    base = load("baseline-basic-rag.yaml")
    for name, expected in {
        "phase3-1-decomposition.yaml": {
            "run_name": "phase3-1-decomposition",
            "target.factory": "archagenticrag.graphs.decompose_rag:build_graph",
            "target.record_keys": ["sub_questions"],
            "system.decomposition": {"max_sub_questions": 3, "max_context_chunks": 8},
        },
        "control-b1-topk8.yaml": {"run_name": "control-b1-topk8", "system.retrieval.top_k": 8},
        "control-b2-mmr.yaml": {
            "run_name": "control-b2-mmr",
            "system.retrieval.search_type": "mmr",
            "system.retrieval.fetch_k": 20,
        },
    }.items():
        cfg = load(name)
        diffs = {}

        def walk(a, b, path=""):
            for key in set(a) | set(b):
                p = f"{path}.{key}" if path else key
                if isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
                    walk(a[key], b[key], p)
                elif a.get(key) != b.get(key):
                    diffs[p] = b.get(key)

        walk(base, cfg)
        assert diffs == expected, name
        load_config(REPO_ROOT / "eval/configs" / name)  # valid config


# 8. decomposer failure -> fall back to the original question, error recorded
def test_decomposer_failure_falls_back_and_is_recorded(indexed, decomposition_system, fake_embeddings):
    graph, llm = _graph(indexed, decomposition_system, fake_embeddings, fail=True)
    out = graph.invoke({"question": QUESTION})
    assert out["sub_questions"] == [QUESTION]
    assert "invalid JSON" in out["decomposition_error"]
    assert out["documents"] and out["answer"] == "79 characters."


def test_max_one_sub_question_skips_the_decomposer(indexed, decomposition_system, fake_embeddings):
    decomposition_system["decomposition"]["max_sub_questions"] = 1
    graph, llm = _graph(indexed, decomposition_system, fake_embeddings, proposals=["never used?"])
    out = graph.invoke({"question": QUESTION})
    assert out["sub_questions"] == [QUESTION] and llm.decompose_calls == []
