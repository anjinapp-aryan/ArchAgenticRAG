"""Basic RAG graph: START -> retrieve -> generate -> END.

The node structure follows the official LangGraph RAG examples (langchain-ai/langgraph,
examples/rag/langgraph_crag.ipynb, MIT): a `retrieve` node calls a retriever and a
`generate` node runs prompt | llm | StrOutputParser over the formatted documents.
Everything after retrieval in that example (grading, rewriting, web search) is left out on purpose.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from archagenticrag.rag.settings import RAGSettings, parse_settings

SYSTEM_PROMPT = (
    "You are a question-answering assistant. Answer the user's question using only the "
    "numbered context passages provided below.\n"
    "- Do not use outside knowledge and do not invent facts.\n"
    "- If the context does not contain the information needed to answer, say clearly that "
    "the provided documents do not contain the answer.\n"
    "- Keep the answer concise.\n\n"
    "Context:\n{context}"
)

PROMPT = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", "{question}")])


class RAGState(TypedDict, total=False):
    question: str
    documents: list[Document]
    context: str
    answer: str


def format_documents(documents: list[Document]) -> str:
    """Number each passage and label it with its source, so the model can tell passages apart."""
    if not documents:
        return "(no passages retrieved)"
    blocks = []
    for i, doc in enumerate(documents, start=1):
        label = doc.metadata.get("doc_id", "unknown")
        section = doc.metadata.get("section")
        blocks.append(f"[{i}] ({label}{' › ' + section if section else ''})\n{doc.page_content}")
    return "\n\n".join(blocks)


def build_graph(
    system: dict[str, Any],
    *,
    client: Any = None,
    embeddings: Embeddings | None = None,
    llm: BaseChatModel | None = None,
):
    """Build the Basic RAG graph from the `system` config section.

    ``client``, ``embeddings`` and ``llm`` can be injected (tests); by default they are
    built from the settings: a Qdrant server client, FastEmbed embeddings, and a chat model
    from the configured provider. The returned compiled graph carries ``eval_metadata``
    describing the index it reads from, for the evaluation run manifest.
    """
    from archagenticrag.providers import chat_model
    from archagenticrag.rag.vector_store import make_client, make_embeddings, open_store

    settings: RAGSettings = parse_settings(system)
    client = client if client is not None else make_client(settings.retrieval.qdrant)
    embeddings = embeddings if embeddings is not None else make_embeddings(settings.embedding)
    llm = llm if llm is not None else chat_model(
        settings.generator.provider, settings.generator.model, settings.generator.temperature
    )

    store, index_meta = open_store(client, settings, embeddings)
    retriever = store.as_retriever(search_type="similarity", search_kwargs={"k": settings.retrieval.top_k})
    answer_chain = PROMPT | llm | StrOutputParser()

    def retrieve(state: RAGState, config: RunnableConfig) -> RAGState:
        documents = retriever.invoke(state["question"], config=config)
        return {"documents": documents, "context": format_documents(documents)}

    def generate(state: RAGState, config: RunnableConfig) -> RAGState:
        answer = answer_chain.invoke({"context": state["context"], "question": state["question"]}, config=config)
        return {"answer": answer}

    builder = StateGraph(RAGState)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)
    graph = builder.compile(name="basic_rag")
    graph.eval_metadata = {"graph": "basic_rag", "index": index_meta, "prompt": SYSTEM_PROMPT}
    return graph
