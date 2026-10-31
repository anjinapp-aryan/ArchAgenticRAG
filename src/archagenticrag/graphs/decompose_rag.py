"""Phase 3.1 graph: query decomposition with parallel per-sub-question retrieval.

START -> decompose -> (Send x N) retrieve_one -> merge -> generate -> END

Design: docs/PHASE-3.1-DESIGN.md. The only change from Basic RAG is on the query side of
retrieval. ``generate`` (node, prompt, model) is the Basic RAG one, unchanged.

Adapted (MIT) from GiovanniPasq/agentic-rag-for-dummies @ 394c4f7,
project/rag_agent/{schemas,prompts,edges}.py: the sub-question schema shape, the
"split only truly separate information needs, at most 3" rules, and one ``Send`` per
sub-question. Their clarification branch, agent/tool loop and per-sub-question answering are
deliberately not part of this phase.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from archagenticrag.graphs.basic_rag import PROMPT, SYSTEM_PROMPT, format_documents, make_retriever
from archagenticrag.rag.settings import RAGSettings, SettingsError, parse_settings

DECOMPOSE_SYSTEM_PROMPT = (
    "You split a user question into self-contained search queries for a document retriever.\n"
    "- If the question has a single information need, return no sub-questions.\n"
    "- Split only truly separate information needs, for example two different documents, "
    "proposals or facts asked about in one question, with a maximum of {max_extra} sub-questions.\n"
    "- Each sub-question must be self-contained and focused on one information need.\n"
    "- Preserve names, PEP numbers, identifiers, versions and technical terms exactly.\n"
    "- Do not add facts, do not answer the question, do not guess answers, and do not "
    "broaden the user's meaning."
)

DECOMPOSE_PROMPT = ChatPromptTemplate.from_messages([("system", DECOMPOSE_SYSTEM_PROMPT), ("human", "{question}")])


class SubQuestions(BaseModel):
    """Structured output of the decompose node."""

    sub_questions: list[str] = Field(
        default_factory=list,
        description="Self-contained search queries, one per separate information need. Empty if the question has a single need.",
    )


class RetrievalHit(TypedDict):
    sub_question_index: int  # 0 = the original question
    documents: list[Document]


class DecomposeRAGState(TypedDict, total=False):
    question: str
    sub_questions: list[str]  # original question first
    decomposition_error: str | None  # set when the decomposer failed and we fell back
    retrieved: Annotated[list[RetrievalHit], operator.add]  # filled by parallel retrieve_one
    documents: list[Document]
    context: str
    answer: str


class RetrieveOneInput(TypedDict):
    sub_question: str
    sub_question_index: int


def normalize_sub_questions(question: str, proposed: list[str], max_sub_questions: int) -> list[str]:
    """Original question first; then distinct, non-blank proposals; at most ``max_sub_questions``."""
    result = [question]
    seen = {" ".join(question.lower().split())}
    for candidate in proposed:
        text = " ".join((candidate or "").split())
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result[:max_sub_questions]


def merge_hits(hits: list[RetrievalHit], max_chunks: int) -> list[Document]:
    """Unique union by chunk_id: the original question's hits first, then the other
    sub-questions' hits taken in turn (rank 1 of each, then rank 2, ...), capped at ``max_chunks``."""
    by_index: dict[int, list[Document]] = {}
    for hit in hits:
        by_index.setdefault(hit["sub_question_index"], []).extend(hit["documents"])
    ordered = list(by_index.get(0, []))
    others = [by_index[i] for i in sorted(by_index) if i != 0]
    for rank in range(max((len(docs) for docs in others), default=0)):
        ordered.extend(docs[rank] for docs in others if rank < len(docs))

    merged: list[Document] = []
    seen: set[str] = set()
    for doc in ordered:
        key = doc.metadata.get("chunk_id") or doc.page_content
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)
        if len(merged) == max_chunks:
            break
    return merged


def build_graph(
    system: dict[str, Any],
    *,
    client: Any = None,
    embeddings: Embeddings | None = None,
    llm: BaseChatModel | None = None,
):
    """Build the Phase 3.1 graph from the ``system`` config section (needs ``system.decomposition``).

    ``client``, ``embeddings`` and ``llm`` can be injected (tests). The decompose node uses the
    same chat model as ``generate``, so no new model enters the comparison with Basic RAG.
    """
    from archagenticrag.providers import chat_model
    from archagenticrag.rag.vector_store import make_client, make_embeddings, open_store

    settings: RAGSettings = parse_settings(system)
    if settings.decomposition is None:
        raise SettingsError("system.decomposition is required for the Phase 3.1 decomposition graph")
    decomposition = settings.decomposition
    client = client if client is not None else make_client(settings.retrieval.qdrant)
    embeddings = embeddings if embeddings is not None else make_embeddings(settings.embedding)
    llm = llm if llm is not None else chat_model(
        settings.generator.provider,
        settings.generator.model,
        settings.generator.temperature,
        strategy=settings.provider_strategy,
    )

    store, index_meta = open_store(client, settings, embeddings)
    retriever = make_retriever(store, settings)
    decompose_chain = DECOMPOSE_PROMPT.partial(max_extra=decomposition.max_sub_questions - 1) | llm.with_structured_output(
        SubQuestions
    )
    answer_chain = PROMPT | llm | StrOutputParser()

    def decompose(state: DecomposeRAGState, config: RunnableConfig) -> DecomposeRAGState:
        question = state["question"]
        if decomposition.max_sub_questions == 1:
            return {"sub_questions": [question], "decomposition_error": None}
        try:
            result = decompose_chain.invoke({"question": question}, config=config)
            proposed = result.sub_questions if isinstance(result, SubQuestions) else []
            error = None
        except Exception as exc:  # recorded in state; retrieval still runs for the original question
            proposed, error = [], f"{type(exc).__name__}: {exc}"
        return {
            "sub_questions": normalize_sub_questions(question, proposed, decomposition.max_sub_questions),
            "decomposition_error": error,
        }

    def fan_out(state: DecomposeRAGState) -> list[Send]:
        return [
            Send("retrieve_one", {"sub_question": q, "sub_question_index": i})
            for i, q in enumerate(state["sub_questions"])
        ]

    def retrieve_one(state: RetrieveOneInput, config: RunnableConfig) -> DecomposeRAGState:
        documents = retriever.invoke(state["sub_question"], config=config)
        return {"retrieved": [{"sub_question_index": state["sub_question_index"], "documents": documents}]}

    def merge(state: DecomposeRAGState) -> DecomposeRAGState:
        documents = merge_hits(state.get("retrieved", []), decomposition.max_context_chunks)
        return {"documents": documents, "context": format_documents(documents)}

    def generate(state: DecomposeRAGState, config: RunnableConfig) -> DecomposeRAGState:
        answer = answer_chain.invoke({"context": state["context"], "question": state["question"]}, config=config)
        return {"answer": answer}

    builder = StateGraph(DecomposeRAGState)
    builder.add_node("decompose", decompose)
    builder.add_node("retrieve_one", retrieve_one)
    builder.add_node("merge", merge)
    builder.add_node("generate", generate)
    builder.add_edge(START, "decompose")
    builder.add_conditional_edges("decompose", fan_out, ["retrieve_one"])
    builder.add_edge("retrieve_one", "merge")
    builder.add_edge("merge", "generate")
    builder.add_edge("generate", END)
    graph = builder.compile(name="decompose_rag")
    graph.eval_metadata = {
        "graph": "decompose_rag",
        "index": index_meta,
        "prompt": SYSTEM_PROMPT,
        "decompose_prompt": DECOMPOSE_SYSTEM_PROMPT,
        "decomposition": decomposition.model_dump(),
    }
    return graph
