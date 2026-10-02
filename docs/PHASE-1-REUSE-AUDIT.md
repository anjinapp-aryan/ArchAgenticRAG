# Phase 1: Reuse Audit (Basic RAG)

**Date:** 2026-10-01.

**How each item was verified**

| Tag | Meaning |
|---|---|
| **[PYPI]** | Version taken from the PyPI JSON API. |
| **[INSTALLED]** | Installed in the project venv and its API inspected or executed. |
| **[SRC]** | Source files read in a pinned clone. |
| **[RUN]** | Exercised against the real local stack (Qdrant server, FastEmbed, Docling, provider APIs). |

## 1. Repository findings before Phase 1

At the start of Phase 1, `d:\WORK_SPACE\ArchAgenticRAG` was **not a git repository**. It contained only the Phase 0 and Phase 2 work:

- `docs/`
- `eval/`
- `data/corpus/peps/`
- `src/archagenticrag/evaluation/`
- `tests/evaluation/`
- `pyproject.toml`

No `graphs/`, ingestion, vector store or LLM code existed. A search for `basic_rag`, `build_graph`, LangGraph, Qdrant, Docling, embedding, retriever and Ollama found only references in docs and the evaluation config.

**What existed and was reused:**

- **Provider presets** (`evaluation/providers.py`). They were moved to `archagenticrag/providers.py` so the graph and the evaluator share them. The old module still re-exports them, and an `ollama` preset was added.
- **The evaluation contract** (`target.factory`, input/output keys, `Document.metadata["doc_id"]`).
- **The pinned corpus with manifest hashes.**

**What was not touched:**

- the golden dataset and its evidence quotes
- the corpus files
- metric selection and triage rules
- the Ragas and Langfuse integration

### Phase 2 code changes (all additive)

1. `target.py`:
   - It now also times LLM calls (`generation_latency_s`), via the same LangChain callback that already timed retrievers.
   - Its import-error message no longer says "Phase 1 missing", which became false.
2. `runner.py`: records `target.eval_metadata`, which holds the index description, in the run manifest.
3. `analysis.py`: adds retrieval and generation latency percentiles to the summary.
4. One Phase 2 test was retargeted. `test_missing_phase1_graph_gives_clear_error` asserted that the graph did *not* exist. It became `test_missing_target_module_gives_clear_error` and `test_missing_target_function_gives_clear_error`.

## 2. Decision table

| Capability | Candidate | License | Version | Decision | Reason |
|---|---|---|---|---|---|
| Orchestration | LangGraph | MIT | 1.2.12 [PYPI][RUN] | **REUSE** | `StateGraph` with `retrieve` → `generate`, as in the official examples. |
| Basic RAG pattern | langchain-ai/langgraph `examples/rag/langgraph_crag.ipynb` | MIT | commit `4be610c` [SRC] | **ADAPT** (pattern) | Canonical `retrieve` / `generate` nodes and `format_docs`. Grading, rewriting and web search are left out. |
| Document parsing | Docling (`docling-slim` HTML backend) | MIT | 2.131.0 [INSTALLED][RUN] | **REUSE** | HTML → `DoclingDocument` (headings, paragraphs, code, lists). |
| RST → HTML | docutils PEP reader + `html4css1` writer | Public domain / BSD-2 (PEP reader) | 0.23 [INSTALLED][RUN] | **REUSE / COMPOSE** | Docling has **no reStructuredText backend** (verified: `InputFormat` lists 35 formats, none of them RST). docutils is the reference RST implementation and ships a PEP reader that parses the RFC 2822 header. |
| Chunking | Docling `HybridChunker` + `HuggingFaceTokenizer` | MIT | docling-core 2.99.0 [RUN] | **REUSE** | Heading-aware, token-bounded chunks, sized with the embedding model's tokenizer. |
| Embeddings | FastEmbed via `langchain_community.embeddings.FastEmbedEmbeddings`, model `BAAI/bge-small-en-v1.5` (ONNX: `Qdrant/bge-small-en-v1.5-onnx-Q` @ `aa8f8b0`) | Apache-2.0 (FastEmbed), MIT (model card) | fastembed 0.8.1 [RUN] | **REUSE** | Local, CPU, no API key, no server, 384 dimensions. It needs no torch, so the install stays slim. |
| Vector DB | Qdrant server (`qdrant/qdrant:v1.19.1`, Docker) | Apache-2.0 | 1.19.1 [RUN] | **REUSE** | Phase 0 choice. Collection-level `metadata` stores the index description next to the index. |
| Vector store API | `langchain-qdrant` `QdrantVectorStore` | MIT | 1.1.0 [RUN] | **REUSE** | `add_documents`, `as_retriever`, `validate_collection_config` (size and distance checks). |
| Retrieval | `QdrantVectorStore.as_retriever(search_type="similarity", k=top_k)` | MIT | 1.1.0 [RUN] | **REUSE** | Dense cosine similarity only. As a LangChain retriever it emits the callbacks the evaluator times. |
| Collection guard | GiovanniPasq/agentic-rag-for-dummies `project/db/vector_db_manager.py` | MIT | commit `2461e52` [SRC] | **ADAPT** (pattern) | Idea reused: refuse an index whose vector size does not match the embedding model. Reimplemented for server mode, dense only, and extended to check the embedding model and chunking settings recorded in the collection metadata. No code was copied. |
| LLM (local) | Ollama via its OpenAI-compatible `/v1` API | MIT (Ollama) | — | **REUSE** (supported, not used for the baseline) | `provider: ollama` works through the same `ChatOpenAI` client. **Ollama is not installed on this machine.** At the user's direction the baseline uses API providers. |
| LLM (API) | `langchain-openai` `ChatOpenAI` against OpenAI-compatible endpoints (Groq, Gemini, NVIDIA, OpenRouter, xAI, OpenAI) | MIT | 1.6.7 [RUN] | **REUSE** | One client class for every provider. The "provider abstraction" is a 7-entry preset table. |
| Tracing | Langfuse | MIT (SDK) | 4.16.0 | **REUSE** (deferred) | Same status as Phase 2: the offline `run_experiment` path is used, and the self-hosted server is not started yet. |

### Rejected or not used

| Candidate | Reason |
|---|---|
| `langchain-docling` 3.0.0 (`DoclingLoader`) | It was installed for inspection and then removed. It wraps the converter and chunker we already call directly, and it cannot help with the RST gap. |
| agentic-rag-for-dummies chunking (Markdown header splitter + parent/child) | Parent/child retrieval is an optimization for a later phase. Phase 1 uses Docling's standard chunker. |
| agentic-rag-for-dummies hybrid (dense + BM25) retrieval | Hybrid search is a Phase 3+ experiment. The baseline is dense only. |
| `rlm/rag-prompt` from LangChain Hub (used by the LangGraph examples) | Licensing of hub prompts is unclear, and it lacks the "say when the context does not contain the answer" instruction. We wrote our own short prompt instead. |
| sentence-transformers / HuggingFaceEmbeddings | They pull in torch (GBs). FastEmbed gives the same `bge-small` model through ONNX. |
| Qdrant embedded (`QdrantClient(path=...)`) | Used only in offline tests (`:memory:`). The baseline uses the real server, as the brief requires. |

## 3. Adapted open-source implementations

### 1. langchain-ai/langgraph (MIT)

- **URL:** https://github.com/langchain-ai/langgraph
- **Commit:** `4be610c6bc7c042038f671d6def9f523ca385a69`
- **Source files:** `examples/rag/langgraph_crag.ipynb`, `examples/rag/langgraph_agentic_rag.ipynb`
- **What was reused:** the shape of the graph state (`question`, `documents`, generation), a `retrieve` node calling `retriever.invoke`, a `generate` node running `prompt | llm | StrOutputParser()`, and joining `page_content` for the context.
- **What was changed:**
  - The answer key is renamed `answer`, to match the Phase 2 contract.
  - `context` was added to the state.
  - Passages are numbered and labelled with their source.
  - Our own system prompt replaces `hub.pull("rlm/rag-prompt")`.
  - Grading, rewriting and web search were removed.
  - `RunnableConfig` is passed into every call so callbacks propagate.

### 2. GiovanniPasq/agentic-rag-for-dummies (MIT, © 2025 Giovanni Pasqualino)

- **URL:** https://github.com/GiovanniPasq/agentic-rag-for-dummies
- **Commit:** `2461e5251c6b9a6be71d13176ab43301f3c0a068`
- **Source file:** `project/db/vector_db_manager.py`
- **What was reused:** the *pattern* of checking an existing collection's vector size against the embedding model before use, and failing with an instruction to re-index.
- **What was changed:** reimplemented for `QdrantClient(url=...)` with dense vectors only. The check is extended to the embedding model name and chunking settings, which are stored in the Qdrant collection metadata. No code was copied.

## 4. Composition problems found and solved

1. **Docling cannot read reStructuredText.** Fix: docutils PEP reader → HTML → Docling.
2. **Docling skipped the PEP header.**
   - When rendered as an HTML definition list (docutils `html5` writer), the header disappeared.
   - When rendered as a table (`html4css1`), Docling parsed all 12 rows, but `HybridChunker` emitted nothing for it.
   - The root cause was that Docling's HTML backend labels everything before the first heading as `ContentLayer.FURNITURE`, and chunkers read only the body layer. This was verified by inspecting `content_layer` on the parsed items.
   - Fix: the header field list becomes `Field: value` paragraphs, and the document gets its real title (`PEP 563 - Postponed Evaluation of Annotations`) as `<h1>`, the same way peps.python.org renders it. Golden items about Status, Superseded-By and Python-Version depend on this.
3. **Hyperlinks fragmented chunk text.** Docling's chunk serializer put each inline link on its own line as Markdown (`[PEP 484](https://…)`). Fix: references are unwrapped to plain text in the docutils tree before rendering.
4. **The auto-generated table of contents** became a navigation-only chunk. Fix: removed in the docutils tree.
5. **CRLF line endings on Windows git** would have changed the corpus bytes and broken the manifest hashes. Fix: `.gitattributes` marks `data/corpus/**` as `-text`.
