"""Experiment 03 cross-encoder reranking (docs/EXPERIMENT-03-RERANKING-AUDIT.md).

Inference is FastEmbed's ``TextCrossEncoder`` (ONNX on CPU, the runtime the embeddings already
use). This adapter only exposes it as a LangChain document compressor, so LangChain's
``ContextualCompressionRetriever`` can compose it with the hybrid candidate retriever. The score
goes into ``metadata["relevance_score"]``, which the retrieval trace already reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from pydantic import ConfigDict


class FastEmbedRerank(BaseDocumentCompressor):
    """Scores every candidate against the query and keeps the ``top_n`` best.

    Equal scores keep their candidate order, so the result is deterministic for a given input.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    encoder: Any  # anything with rerank(query, documents) -> scores, e.g. fastembed TextCrossEncoder
    top_n: int

    def compress_documents(
        self, documents: Sequence[Document], query: str, callbacks: Callbacks | None = None
    ) -> Sequence[Document]:
        if not documents:
            return []
        scores = [float(s) for s in self.encoder.rerank(query, [d.page_content for d in documents])]
        if len(scores) != len(documents):
            raise ValueError(f"reranker returned {len(scores)} scores for {len(documents)} documents")
        order = sorted(range(len(documents)), key=lambda i: (-scores[i], i))[: self.top_n]
        return [
            Document(page_content=documents[i].page_content, metadata={**documents[i].metadata, "relevance_score": scores[i]})
            for i in order
        ]


def make_encoder(model: str) -> Any:
    """FastEmbed cross-encoder on CPU. The model is downloaded once to ``FASTEMBED_CACHE_PATH``."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model)
