"""Real local stack: Docling ingestion -> FastEmbed -> Qdrant server -> retrieval.

Run with: pytest -m integration   (needs `docker compose up -d qdrant`)
Uses its own collection, so it never touches the baseline index.
"""

from __future__ import annotations

import pytest

from archagenticrag.rag.ingestion import chunk_corpus
from archagenticrag.rag.settings import parse_settings
from archagenticrag.rag.vector_store import embedding_dimension, index_documents, make_client, make_embeddings, open_store

from ..rag.conftest import CORPUS_DIR

pytestmark = pytest.mark.integration

COLLECTION = "test_integration_peps"


@pytest.fixture(scope="module")
def settings():
    import copy

    import yaml

    from ..rag.conftest import BASELINE_CONFIG

    system = copy.deepcopy(yaml.safe_load(BASELINE_CONFIG.read_text(encoding="utf-8"))["system"])
    system["retrieval"]["qdrant"]["collection"] = COLLECTION
    return parse_settings(system)


@pytest.fixture(scope="module")
def client(settings):
    client = make_client(settings.retrieval.qdrant)
    try:
        client.get_collections()
    except Exception as exc:  # pragma: no cover - environment
        pytest.skip(f"Qdrant server not reachable at {settings.retrieval.qdrant.url}: {exc}")
    yield client
    client.delete_collection(COLLECTION)


@pytest.fixture(scope="module")
def embeddings(settings):
    return make_embeddings(settings.embedding)


@pytest.fixture(scope="module")
def chunks(settings):
    documents, _, report = chunk_corpus(CORPUS_DIR, settings.chunking)
    return documents, report


@pytest.fixture(scope="module")
def store(client, settings, embeddings, chunks):
    documents, _ = chunks
    index_documents(client, settings, embeddings, documents, {"corpus_id": "peps-v1"})
    store, _ = open_store(client, settings, embeddings)
    return store


def test_local_embeddings_have_configured_dimension(embeddings, settings):
    assert embedding_dimension(embeddings) == settings.retrieval.embedding_dimension == 384
    vectors = embeddings.embed_documents(["a", "b"])
    assert len(vectors) == 2 and len(vectors[0]) == 384


def test_docling_chunks_every_document_with_metadata(chunks):
    documents, report = chunks
    assert report.documents == 13
    assert all(n > 0 for n in report.chunks_per_document.values())
    for doc in documents:
        assert {"doc_id", "source", "title", "section", "chunk_id"} <= set(doc.metadata)
        assert doc.page_content.startswith("PEP ")
    # every PEP's header (Title/Status) is retrievable text
    for doc_id in report.chunks_per_document:
        assert any(d.metadata["doc_id"] == doc_id and "Status: " in d.page_content for d in documents), doc_id


def test_chunks_fit_the_embedding_model_window(chunks):
    from transformers import AutoTokenizer

    documents, _ = chunks
    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
    assert max(len(tokenizer(d.page_content)["input_ids"]) for d in documents) <= 512


def test_qdrant_collection_holds_all_chunks(client, store, chunks):
    documents, _ = chunks
    assert client.count(COLLECTION, exact=True).count == len(documents)


@pytest.mark.parametrize(
    ("query", "expected_doc"),
    [
        ("How long may a line of Python code be in the style guide?", "pep-0008"),
        ("What is the walrus operator?", "pep-0572"),
        ("lazily computing annotations on demand with a new object method", "pep-0649"),
        ("Which file stores build system dependencies?", "pep-0518"),
    ],
)
def test_known_questions_retrieve_the_relevant_document(store, settings, query, expected_doc):
    hits = store.similarity_search(query, k=settings.retrieval.top_k)
    assert expected_doc in [h.metadata["doc_id"] for h in hits]


def test_phase31_fan_out_and_merge_on_the_real_index(store, settings, client, embeddings):
    """Phase 3.1 mechanics on real Qdrant + FastEmbed, with a fixed (fake) decomposer: one retrieval
    per sub-question, original question's hits first, unique chunks, capped at 8. Whether the real
    LLM decomposer improves retrieval is an experiment result, not a test assertion."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.runnables import RunnableLambda

    from archagenticrag.graphs.decompose_rag import SubQuestions, build_graph

    class FixedDecomposer(FakeListChatModel):
        def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ANN003
            return RunnableLambda(lambda _: SubQuestions(sub_questions=["PEP 518 build system requirements"]))

    system = settings.model_dump(mode="json")
    system["decomposition"] = {"max_sub_questions": 3, "max_context_chunks": 8}
    graph = build_graph(system=system, client=client, embeddings=embeddings, llm=FixedDecomposer(responses=["ok"]))
    out = graph.invoke({"question": "What does PEP 621 store in pyproject.toml?"})

    doc_ids = [d.metadata["doc_id"] for d in out["documents"]]
    chunk_ids = [d.metadata["chunk_id"] for d in out["documents"]]
    assert out["sub_questions"] == ["What does PEP 621 store in pyproject.toml?", "PEP 518 build system requirements"]
    assert len(chunk_ids) == len(set(chunk_ids)) <= 8
    assert {"pep-0518", "pep-0621"} <= set(doc_ids)
    original = [d.metadata["chunk_id"] for d in store.similarity_search(out["sub_questions"][0], k=settings.retrieval.top_k)]
    assert chunk_ids[: len(original)] == original


# Phase 3.0 experiment-lab infrastructure on the real stack.


def test_committed_qrels_match_a_fresh_chunking_of_the_corpus(chunks):
    """The qrels chunk catalog (chunk id -> text hash) is reproducible from the corpus."""
    from archagenticrag.evaluation.relevance import load_qrels, text_sha256

    from ..evaluation.test_relevance import QRELS_FILE

    documents, _ = chunks
    catalog = load_qrels(QRELS_FILE)["chunk_catalog"]
    assert {d.metadata["chunk_id"]: text_sha256(d.page_content) for d in documents} == {k: v["sha256"] for k, v in catalog.items()}


def test_committed_qrels_match_the_baseline_collection(client):
    """Read-only check that the baseline index holds exactly the chunks the qrels describe."""
    from archagenticrag.evaluation.relevance import load_qrels, text_sha256

    from ..evaluation.test_relevance import QRELS_FILE

    qrels = load_qrels(QRELS_FILE)
    name = qrels["chunk_set"]["collection"]
    if not client.collection_exists(name):
        pytest.skip(f"baseline collection {name} not indexed on this machine")
    points, offset = [], None
    while True:
        batch, offset = client.scroll(name, limit=256, offset=offset, with_payload=True, with_vectors=False)
        points += batch
        if offset is None:
            break
    stored = {p.payload["metadata"]["chunk_id"]: text_sha256(p.payload["page_content"]) for p in points}
    assert stored == {k: v["sha256"] for k, v in qrels["chunk_catalog"].items()}


async def test_retrieval_instrumentation_on_the_real_basic_rag_graph(store, settings, client, embeddings):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from archagenticrag.evaluation.config import TargetRef
    from archagenticrag.evaluation.target import run_target
    from archagenticrag.graphs.basic_rag import build_graph

    graph = build_graph(system=settings.model_dump(mode="json"), client=client, embeddings=embeddings, llm=FakeListChatModel(responses=["ok"]))
    res = await run_target(graph, TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph"), "What is the walrus operator?")
    assert res.error is None
    assert [r["rank"] for r in res.retrieval_results] == [1, 2, 3, 4]
    assert all(r["chunk_id"] and r["doc_id"] for r in res.retrieval_results)
    assert all(r["score"] is None for r in res.retrieval_results)  # similarity retriever exposes no score
    assert {r["method"] for r in res.retrieval_results} == {"VectorStoreRetriever(QdrantVectorStore)"}
    (call,) = res.retrieval_calls
    assert call["query"] == "What is the walrus operator?" and call["latency_s"] > 0
    assert [h["chunk_id"] for h in call["results"]] == [r["chunk_id"] for r in res.retrieval_results]


# Experiment 02 hybrid retrieval on the real stack (read-only on both collections).

EXP02_CONFIG = "eval/configs/exp02-hybrid-bm25.yaml"


def _exp02_settings():
    from archagenticrag.evaluation.config import load_config

    from ..rag.conftest import REPO_ROOT

    return parse_settings(load_config(REPO_ROOT / EXP02_CONFIG).system.model_dump(mode="json"))


def _scroll_hashes(client, name):
    from archagenticrag.evaluation.relevance import text_sha256

    points, offset = [], None
    while True:
        batch, offset = client.scroll(name, limit=256, offset=offset, with_payload=True, with_vectors=False)
        points += batch
        if offset is None:
            return {p.payload["metadata"]["chunk_id"]: text_sha256(p.payload["page_content"]) for p in points}


def test_hybrid_collection_is_separate_and_the_baseline_collection_stays_dense(client):
    from archagenticrag.evaluation.relevance import load_qrels
    from archagenticrag.rag.vector_store import SPARSE_VECTOR_NAME

    from ..evaluation.test_relevance import QRELS_FILE

    hybrid = _exp02_settings().retrieval.qdrant.collection
    baseline = load_qrels(QRELS_FILE)["chunk_set"]["collection"]
    for name in (hybrid, baseline):
        if not client.collection_exists(name):
            pytest.skip(f"collection {name} not indexed on this machine")
    assert hybrid != baseline
    base_info, hybrid_info = client.get_collection(baseline), client.get_collection(hybrid)
    assert not base_info.config.params.sparse_vectors and "retrieval_mode" not in base_info.config.metadata
    assert str(hybrid_info.config.params.sparse_vectors[SPARSE_VECTOR_NAME].modifier).lower().endswith("idf")
    # same chunks, same text: the Phase 3.0 qrels apply to both
    catalog = {k: v["sha256"] for k, v in load_qrels(QRELS_FILE)["chunk_catalog"].items()}
    assert _scroll_hashes(client, hybrid) == catalog == _scroll_hashes(client, baseline)


def test_bm25_branch_matches_an_exact_pep_number(client):
    from archagenticrag.rag.vector_store import SPARSE_VECTOR_NAME, make_sparse_embeddings
    from qdrant_client.http import models as qm

    settings = _exp02_settings()
    if not client.collection_exists(settings.retrieval.qdrant.collection):
        pytest.skip("hybrid collection not indexed")
    query = make_sparse_embeddings(settings.retrieval.sparse).embed_query("PEP 518 build system requirements")
    hits = client.query_points(
        settings.retrieval.qdrant.collection,
        query=qm.SparseVector(indices=query.indices, values=query.values),
        using=SPARSE_VECTOR_NAME,
        limit=4,
        with_payload=True,
    ).points
    assert hits[0].payload["metadata"]["doc_id"] == "pep-0518"


async def test_hybrid_graph_on_the_real_index_records_the_fused_ranking(client, embeddings):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from archagenticrag.evaluation.config import TargetRef
    from archagenticrag.evaluation.target import run_target
    from archagenticrag.graphs.basic_rag import HYBRID_METHOD, build_graph

    settings = _exp02_settings()
    if not client.collection_exists(settings.retrieval.qdrant.collection):
        pytest.skip("hybrid collection not indexed")
    graph = build_graph(system=settings.model_dump(mode="json"), client=client, embeddings=embeddings, llm=FakeListChatModel(responses=["ok"]))
    res = await run_target(graph, TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph"), "What is the walrus operator?")
    assert res.error is None
    assert [r["rank"] for r in res.retrieval_results] == [1, 2, 3, 4]  # final fused list = top_k, as in the baseline
    assert {r["method"] for r in res.retrieval_results} == {HYBRID_METHOD}
    assert all(r["chunk_id"] and r["doc_id"] for r in res.retrieval_results)
    assert graph.eval_metadata["index"]["retrieval_mode"] == "hybrid"


# Multi-provider fallback on the real graph and index; the providers are mocked (no quota used).


def _graph_with_mocked_providers(client, embeddings, settings, monkeypatch, script):
    import httpx

    from archagenticrag import providers
    from archagenticrag.graphs.basic_rag import build_graph

    from ..test_provider_fallback import KEYS, Providers

    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)
    mocked = Providers(script)
    original = providers.fallback_transport
    monkeypatch.setattr(providers, "fallback_transport", lambda *a, **k: original(*a[:4], inner=httpx.MockTransport(mocked)))
    system = settings.model_dump(mode="json")
    system["generator"] = {"provider": "gemini", "model": "gemini-2.5-flash", "temperature": 0}
    system["provider_strategy"] = {
        "mode": "fallback",
        "fallbacks": [{"provider": "cerebras", "model": "llama-3.3-70b"}, {"provider": "groq", "model": "openai/gpt-oss-120b"}],
        "retry_backoff_s": 0,
    }
    return build_graph(system=system, client=client, embeddings=embeddings), mocked


async def test_real_graph_gemini_429_cerebras_429_groq_success(store, settings, client, embeddings, monkeypatch):
    from archagenticrag.evaluation.config import TargetRef
    from archagenticrag.evaluation.target import run_target

    from ..test_provider_fallback import err

    graph, mocked = _graph_with_mocked_providers(
        client, embeddings, settings, monkeypatch, {"gemini": [(429, err("quota"), {})], "cerebras": [(429, err("busy"), {})]}
    )
    res = await run_target(graph, TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph"), "What is the walrus operator?")
    assert res.error is None and res.answer == "from groq"
    assert len(res.retrieval_results) == 4  # retrieval unaffected
    (call,) = res.provider_calls
    assert (call["primary_provider"], call["actual_provider"], call["actual_model"]) == ("gemini", "groq", "openai/gpt-oss-120b")
    assert "openai/gpt-oss-120b" in res.usage  # token usage is keyed by the model that actually answered


async def test_real_graph_gemini_auth_error_stops_without_fallback(store, settings, client, embeddings, monkeypatch):
    from archagenticrag.evaluation.config import TargetRef
    from archagenticrag.evaluation.target import run_target

    from ..test_provider_fallback import err

    graph, mocked = _graph_with_mocked_providers(client, embeddings, settings, monkeypatch, {"gemini": [(401, err("API key not valid"), {})]})
    res = await run_target(graph, TargetRef(factory="archagenticrag.graphs.basic_rag:build_graph"), "What is the walrus operator?")
    assert "AuthenticationError: Error code: 401" in res.error  # LangChain wraps it as OpenAIAuthenticationError
    assert mocked.providers_called() == ["gemini"]
    assert res.provider_calls[0]["outcome"] == "error" and res.provider_calls[0]["fallback_used"] is False
