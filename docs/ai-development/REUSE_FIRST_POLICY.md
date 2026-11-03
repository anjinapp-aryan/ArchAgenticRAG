# Reuse-first policy

> **Never reinvent the wheel.** REUSE → ADAPT → COMPOSE → REFERENCE → BUILD.

The procedure is the `reuse-audit` skill. This file holds the policy, the outcome definitions and the project's accumulated decisions, so an audit does not repeat old work.

## Outcomes

| Outcome | Meaning | Typical size |
|---|---|---|
| REUSE | Use an existing component as shipped | config only |
| ADAPT | Thin adapter around an existing component | tens of lines |
| COMPOSE | Combine existing components | glue |
| REFERENCE | Learn from a project, write our own, credit it in `THIRD_PARTY_NOTICES.md` | own code |
| BUILD | Nothing suitable exists; justify why each earlier outcome failed | own code |

Choose the smallest outcome that works. Never copy large amounts of code from another repository. A paid or external API is not an acceptable fallback unless the user decides so.

## What is already here (hints, not a source of truth)

Verify with `pyproject.toml` (pins) and `importlib.metadata`; do not trust this table for versions.

| Capability | Existing component | Where used |
|---|---|---|
| Vector store, dense + sparse + hybrid (RRF) | Qdrant server, `qdrant-client`, `langchain-qdrant` (`RetrievalMode.HYBRID`) | `rag/vector_store.py` |
| Embeddings, BM25 sparse, cross-encoder rerank | `fastembed` (`TextEmbedding`, `Qdrant/bm25`, `TextCrossEncoder`) | `rag/`, `FASTEMBED_CACHE_PATH` |
| Chunking and parsing | `docling-slim` (HybridChunker), `docutils` | `rag/ingestion.py` |
| Graphs, fan-out (`Send`), reducers | `langgraph` | `graphs/` |
| Retriever + compressor composition | `langchain-classic` (`ContextualCompressionRetriever`), `langchain-core` (`BaseDocumentCompressor`) | `graphs/basic_rag.py`, `rag/rerank.py` |
| Chat models for every provider | `langchain-openai` `ChatOpenAI`, `openai` SDK, OpenAI-compatible endpoints | `providers.py` |
| Answer metrics, judge | `ragas`, Groq judge | `evaluation/metrics.py` |
| Ranking metrics | `ir-measures` + `pytrec-eval-terrier` | `evaluation/ranking.py` |
| Tracing, experiment runner | `langfuse` | `evaluation/langfuse_sync.py`, `runner.py` |
| Config validation | `pydantic`, `pyyaml` | everywhere |

## Previously decided: do not re-propose without new evidence

| Option | Decision and reason | Recorded in |
|---|---|---|
| `ranx` for ranking metrics | Not adopted: 13 heavy dependencies for three metrics | `docs/PHASE-3.0-EXPERIMENT-LAB.md` appendix A |
| LiteLLM Router, LangChain `with_fallbacks` for provider fallback | Not adopted: 109 dependencies and a second provider layer; `with_fallbacks` cannot cover the Ragas client | `docs/MULTI-PROVIDER-FALLBACK.md` section 15 |
| `rank_bm25`/BM25S in process, `EnsembleRetriever`, Splade | Not adopted: second sparse engine, client-side fusion, a second variable | `docs/EXPERIMENT-02-HYBRID-RETRIEVAL.md` section 3 |
| `sentence-transformers`, FlagEmbedding, `flashrank`, `rerankers`, paid rerank APIs | Not adopted: torch weight, undeclared licence, duplicate runtimes, paid | `docs/EXPERIMENT-03-RERANKING-AUDIT.md` sections 5 and 17 |
| `Xenova/ms-marco-MiniLM-*` ONNX ports, `jina-reranker-v2` | Rejected: no licence stated on the downloaded repository; non-commercial | `docs/EXPERIMENT-03-RERANKING-AUDIT.md` sections 6 and 15 |
| `onnxruntime-gpu` | Rejected: replaces the CPU runtime behind the frozen embeddings | `docs/EXPERIMENT-03-RERANKING-AUDIT.md` section 17 |
| Changing the Ragas judge model | Not done: the judge is the comparability anchor; a change needs re-judging the baseline and an ADR | `docs/PHASE-3.0-EXPERIMENT-LAB.md` section 9 |

## Precedent audits (use as templates)

`docs/PHASE-1-REUSE-AUDIT.md`, `docs/research/PHASE-2-EVALUATION-REUSE-AUDIT.md`, `docs/EXPERIMENT-03-RERANKING-AUDIT.md`. Decisions worth keeping go in `docs/adr/`.
