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
