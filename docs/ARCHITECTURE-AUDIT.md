# Architecture Audit: Readiness for the RAG Learning Lab

**Date:** 2026-10-27. **Scope:** the code on disk: `main` @ `f5931c3`, plus the uncommitted Phase 3.1 work. It was audited from source, not from READMEs. **Type:** audit only; nothing was implemented.

The audit brief was truncated inside section 11. Sections 1–11 are covered here. Anything the missing part may have asked for (for example a final output format or a stop condition) is not addressed.

## 0. Executive summary

**The current architecture can reach the target without a rewrite.** The shapes already match, under different names:

| Target folder | Already exists as |
|---|---|
| `common/` | `src/archagenticrag/` (`providers.py`, `rag/`, `evaluation/`) |
| `experiments/NN-*` | one graph factory in `graphs/` plus one YAML in `eval/configs/` (`basic_rag`, `decompose_rag`) |
| `datasets/` | `data/corpus/peps/` and `eval/datasets/peps-v1/` |
| `benchmarks/` | `eval/runners/` and `eval/results/` |
| `reports/` | `docs/` |

The existing experiment contract (`build_graph(system=…) → runnable`, input `question`, output `answer` and `documents`) is the right abstraction. A heavier `RAGExperiment` class with `retrieve`/`generate` methods would not fit CRAG, Self-RAG or the agentic patterns.

**The real gaps:**

| Gap | Severity |
|---|---|
| No rank-based retrieval metrics (Recall@K, MRR, nDCG), because the golden set has only document-level relevance and retrieval scores and ranks are not recorded | HIGH |
| No `benchmark --all` / cross-run comparison report | HIGH |
| Judge cost: a full judge pass needs about 1M tokens, so 11 experiments on Groq's free tier take months | **CRITICAL (operational)** |
| Tracing exists only offline: Langfuse runs in no-server mode | MEDIUM |
| Embeddings are local-only (`provider: Literal["local"]`) | MEDIUM |
| Cost is always `null`: no pricing entries | LOW |

**Recommendation.** Do not move files into a `common/` + `experiments/` tree now. The baseline run records `archagenticrag.graphs.basic_rag:build_graph` in its manifest, so moving modules breaks reproduction of the control. Instead:

- add capabilities in place;
- adopt the target names as thin layers (`experiments/NN-name/` holding config plus README, pointing at the factory);
- keep compatibility shims for any module that does move.

## 1. Current architecture (from source)

```text
ArchAgenticRAG/
├── src/archagenticrag/                 ≈ "common platform" (2,239 lines)
│   ├── providers.py                    LLM provider presets (7 OpenAI-compatible endpoints) → ChatOpenAI / AsyncOpenAI
│   ├── rag/
│   │   ├── settings.py                 strict pydantic settings for the `system` config section
│   │   ├── ingestion.py                docutils PEP reader → HTML → Docling → HybridChunker (+ chunk metadata)
│   │   ├── ingest.py                   CLI: corpus → chunks → FastEmbed → Qdrant (+ index manifest in collection metadata)
│   │   └── vector_store.py             Qdrant client, FastEmbed embeddings, index_documents, open_store (index guard)
│   ├── graphs/                         ≈ "experiments"
│   │   ├── basic_rag.py                START → retrieve → generate → END   (Phase 1, the control)
│   │   └── decompose_rag.py            START → decompose → Send×N retrieve_one → merge → generate → END   (Phase 3.1)
│   └── evaluation/                     ≈ "evaluation + benchmark core"
│       ├── config.py                   EvalConfig (dataset, target, system, judge, metrics, triage, pricing) + fingerprint
│       ├── dataset.py                  golden-set schema, corpus traceability check (every evidence quote exists)
│       ├── target.py                   loads factory, invokes graph with callbacks (LLM calls, tokens, latency)
│       ├── metrics.py                  Ragas: faithfulness, relevancy, ctx precision/recall, AnswerCorrectness, 2 DiscreteMetrics
│       ├── analysis.py                 retrieval checks (doc recall, evidence-in-context), triage labels, summary
│       ├── runner.py                   Langfuse run_experiment (offline) → per-item records → results dir
│       ├── resume.py                   finish a run across quota resets
│       ├── tracking.py                 manifest: git, packages, config, fingerprint, dataset/corpus hashes
│       ├── persistence.py, langfuse_sync.py, providers.py (re-export)
├── data/corpus/peps/                   13 PEPs + MANIFEST.json (sha256 per file)
├── eval/
│   ├── datasets/peps-v1/golden.json    42 items, 7 categories, evidence quotes, source_documents
│   ├── configs/*.yaml                  1 per experiment (baseline, 3.1, controls B1, B2)
│   ├── runners/                        run_eval, resume_eval, validate_dataset, sync_langfuse_dataset
│   └── results/<run_id>/               manifest.json, config.yaml, items.jsonl, summary.json   (gitignored)
├── tests/                              evaluation/ (offline), rag/ (offline), integration/ (Qdrant), live (APIs)
├── docs/                               phase reports, ADR 008, reuse audits, learning log
└── docker-compose.yml                  Qdrant only
```

**Dependencies:**

- **Core:** langgraph 1.2.12, langchain-openai, langchain-qdrant, qdrant-client 1.19.1, fastembed 0.8.1, docling-slim, docutils, pydantic.
- **`[eval]` extra:** ragas 0.4.3, langchain-community <0.4, langfuse 4.16.0, openai.

**Flows:**

- **Ingestion (offline):** MANIFEST hash check → docutils → Docling → HybridChunker (480 tokens) → FastEmbed bge-small (384-d) → Qdrant collection, with the index manifest stored as collection metadata.
- **Retrieval:** `make_retriever(store, settings)` → `QdrantVectorStore.as_retriever` (similarity or MMR, `k`). Fires LangChain retriever callbacks.
- **LLM:** `chat_model(provider, model)` → `ChatOpenAI` with a preset base URL and key, `max_retries=6`. The judge uses `AsyncOpenAI` through Ragas `llm_factory`.
- **Evaluation:**
  1. `run_eval.py`: preflight (are the models listed?) → `load_config` → dataset traceability check → `build_target`.
  2. Per item, Langfuse `run_experiment` calls the task (`run_target`), then the evaluator (Ragas).
  3. Triage and summary, then results written to the run directory.
  4. `resume_eval.py` finishes the failed parts in place.
- **Tracing:** LangChain callbacks inside `run_target` (LLM calls, token usage, retriever and LLM time). Langfuse runs offline (`tracing_enabled=False`), so no trace UI exists.
- **Tests:**
  - offline: 141, using a fake LLM, in-memory Qdrant and a mini corpus;
  - integration: 9, using the real Qdrant, Docling and FastEmbed;
  - live: 2, using real Groq.
- **Deployment:** local only, with Docker for Qdrant. There is no service or API layer, and there doesn't need to be one for a lab.

## 2. Current vs target: gap analysis

| Area | Current state | Target state | Gap | Severity | Recommendation |
|---|---|---|---|---|---|
| Common platform | `providers.py`, `rag/`, `evaluation/` already shared by both graphs | `common/{embeddings,vectorstore,llm,retrieval,evaluation,tracing,config}` | Naming and layout only. Retrieval is a single function, not a module. | LOW | Keep the package. Add `rag/retrieval.py` as the retriever factory, not a new tree. |
| Embeddings | FastEmbed only (`EmbeddingSettings.provider: Literal["local"]`); dimension probed and checked against the index | Pluggable providers | No API embeddings for the system under test (the judge already uses Gemini embeddings via OpenAI-compatible) | MEDIUM | Add `provider: openai-compatible` via `langchain_openai.OpenAIEmbeddings` + presets. Only needed if an experiment varies embeddings. |
| Vector store | Qdrant server; collection metadata manifest; guard against model, chunking or dimension mismatch; idempotent indexing | Reusable by all experiments | No sparse vectors, no payload-filter helper. One collection is assumed per (model × chunking). | MEDIUM | Hybrid needs a second, sparse-enabled collection (`langchain-qdrant` `RetrievalMode.HYBRID` + `FastEmbedSparse`, both installed). Name collections by index recipe, as now. |
| LLM abstraction | 7 OpenAI-compatible presets; `ChatOpenAI`; retries 6; structured output via LangChain (used by 3.1) | Select any LLM per experiment | No explicit timeouts; no fallback (deliberate); cost needs pricing entries | LOW | Add a `timeout` setting. Keep "no fallback" for controlled experiments. |
| Retrieval | `make_retriever` → dense similarity or MMR; graph nodes call `retriever.invoke` | Dense, BM25, hybrid, RRF, rerank, multi-query, HyDE, parent/child, contextual | Only dense and MMR. **Scores and ranks are not returned.** | HIGH | Compose LangChain retrievers (section 4.4). Record score and rank in `Document.metadata`. |
| Evaluation | Ragas generation metrics; doc-level recall; evidence-in-context; triage; latency, tokens, LLM calls; resume | Retrieval IR metrics + generation + engineering metrics, same schema for every experiment | **No Recall@K, Precision@K, MRR, nDCG or Hit@K.** No chunk-level relevance judgements. `evidence_in_context` under-reports (raw reStructuredText quotes vs rendered chunks). | HIGH | Map golden evidence quotes to relevant `chunk_id`s once (qrels); compute IR metrics with **ranx** (MIT). |
| Tracing | LangChain callbacks give aggregate counts; Langfuse offline | Question → transformation → retriever → docs + scores → LLM prompt/response → latency, tokens, errors | No per-step trace store or UI; prompts and responses not persisted | MEDIUM | Reuse **Langfuse** (already integrated): start the self-hosted stack, set `langfuse.enabled: true`, add the Langfuse LangChain `CallbackHandler`. Build no custom tracing. |
| Configuration | One YAML per experiment; strict pydantic validation; `.env` keys via presets; config fingerprint and hashes in the manifest; a test asserts experiment configs differ from the baseline only where documented | Centralised, low coupling | Good. Two schemas for one file (`EvalConfig` free-form `system` + `RAGSettings` strict). New optional fields need fingerprint care. | LOW | Keep. Generalise the "diff vs control" test to every experiment config. |
| Dataset management | Corpus pinned (commit + sha256 manifest); golden set versioned, sha in the manifest, traceability-checked | `datasets/{corpus,questions,golden_answers,relevance_judgements}` | **Relevance judgements missing** (document-level only). Questions and answers are in one file, which is fine. | HIGH | Add `qrels.json` (question → relevant chunk_ids), derived from the evidence quotes, versioned with the index recipe. |
| Experiment isolation | Each graph is an independent module; each run is an independent results directory | `experiments/NN-*` independently runnable | No `python -m experiments.x`; run via `run_eval.py <config>`. `decompose_rag` imports helpers from `basic_rag` (prompt, formatting): a sharing dependency, not a runtime one. | LOW | Move shared prompt and format helpers into a `generation` module, so experiments don't import each other. |
| Benchmarking | Per-run summary; manual comparison scripts | `benchmark --all` → one comparison table | No cross-run aggregator; no "same items scored in both" logic in code | HIGH | Add `eval/runners/compare.py` over `results/*/summary.json` + items (paired comparison, NOT RUN for missing runs). |
| Reports | Hand-written phase reports in `docs/` | `reports/` per experiment + overall | No generated report | MEDIUM | Generate the comparison table from `compare.py`; keep the narrative docs by hand. |
| **Judge cost / throughput** | Groq free judge: about 200k tokens/day, so about 9 questions/day; intermittent 1,000 output-tokens/minute rejections | 11 experiments × 42 questions | About 1M judge tokens per run, so roughly 5 days per experiment, about 2 months for all 11 | **CRITICAL** | Decide on judge capacity before scaling (paid tier, local judge, or subset judging). This is the practical limit of the lab, not the code. |

## 3. Common platform audit

### Embeddings
- **Interface:** LangChain `Embeddings` (`embed_documents`, `embed_query`), so the graphs are already provider-agnostic.
- **Provider abstraction:** none for the system under test. `make_embeddings` always builds `FastEmbedEmbeddings`, and the settings forbid anything but `local`.
- **Batching and caching:** FastEmbed batches internally and caches models. There is no embedding cache for queries or documents (not needed at 455 chunks).
- **Dimensionality:** probed (`embedding_dimension`) and checked against both the config and the collection.
- **Verdict:** OpenAI or Gemini embeddings need about 20 lines: a provider field plus `OpenAIEmbeddings(base_url=preset)`. No experiment-specific code is needed.

### Vector store
- Qdrant server, `index_documents` (recreate, deterministic uuid5 point IDs, count check) and `open_store` (refuses a missing, empty or mismatched index). Persistence is via a Docker volume, and it is testable with `:memory:`.
- **Missing:** sparse vectors (hybrid), payload filters (for example `doc_id`), and score output.
- **Verdict:** reusable as is for dense experiments. Hybrid needs one more index recipe, not a new abstraction.

### LLM
- Presets for Ollama, Gemini, OpenRouter, NVIDIA, xAI, Groq and OpenAI. Model and temperature per config. Structured output via `with_structured_output` (works on Groq gpt-oss, verified live). Retries 6.
- Token usage is captured via callbacks. Cost is computed only if `pricing` entries exist, so it is `null` today. Timeouts are not set. There is no fallback, which is the correct choice for controlled experiments.
- **Verdict:** experiments can switch LLMs by config without architectural change.

### Retrieval
- Today: one factory (`make_retriever`) returning a LangChain retriever (similarity or MMR).
- **Recommended boundary:** composition of LangChain `BaseRetriever`s, not one giant class (details in 4.4).

### Evaluation
- **Generation:** correctness, relevance and faithfulness/groundedness via Ragas, plus abstention and clarification.
- **Engineering:** latency (end to end, retrieval, generation), tokens, LLM calls and failure rate (system errors, metric errors) are measured. Cost needs prices.
- **Retrieval IR metrics:** missing. They need qrels and ranked lists.
- **Standard schema:** yes. Every run writes the same `items.jsonl` and `summary.json` regardless of the graph, because `run_target` only reads `answer` and `documents` (plus optional `record_keys`).

### Tracing
- **Captured today:** question, final answer, retrieved documents (text and doc_id), LLM call count, tokens, latency and errors.
- **Not captured:** query transformations (only via `record_keys`), retrieval scores, reranker scores, prompts and responses per call.
- **Verdict:** reuse **Langfuse** (MIT SDK, self-hostable, already a dependency). Its LangChain callback traces every node, prompt, response, token and latency automatically. Do not build custom tracing.

### Configuration
- `.env` holds keys only (gitignored, pre-commit hook). YAML configs hold everything else. Provider presets live in code. The manifest records the full config plus its fingerprint.
- Centralised without heavy coupling. Recommended: keep it, and add a shared "control" base config so each experiment config is a small diff (YAML anchors or an `extends:` key) instead of a full copy.

## 4. Datasets, experiments, contract, benchmark

### 4.1 Dataset architecture
- The same corpus and questions are already reused across runs, with hashes enforced, and a resume refuses a changed dataset. **Fair comparison is guaranteed for corpus, questions and answers.**
- **Problems:**
  1. No chunk-level relevance judgements, so no IR metrics.
  2. Relevance judgements depend on chunking. A chunking experiment would need judgements regenerated from the evidence quotes, which is possible, because quotes are chunking-independent.
  3. `evidence_in_context` matching is broken by RST markup.
- **Recommended layout** (a logical view; physical moves are optional):

```text
datasets/peps-v1/
  corpus/                 = data/corpus/peps (pinned, hashed)
  golden.json             questions + golden answers + evidence quotes (exists)
  qrels/<index-recipe>.json   question → relevant chunk_ids (NEW, generated from evidence quotes)
```

### 4.2 Experiment architecture
Each experiment today is a graph factory plus a config. It runs with:

```bash
python eval/runners/run_eval.py eval/configs/<experiment>.yaml
```

This is the "independently runnable" requirement already met. `python -m experiments.x` would only be sugar.

### 4.3 Experiment contract (recommendation)

**Keep the existing contract.** It is minimal and already proven by 2 graphs:

```text
factory:  build_graph(system: dict, **kwargs) -> Runnable       # LangGraph compiled graph
input:    {"question": str}
output:   {"answer": str, "documents": list[Document]}           # documents = final context
optional: record_keys -> any extra state (sub_questions, grades, routes, iterations)
metadata: graph.eval_metadata = {...}                            # index, prompts, settings
```

| Common (platform) | Experiment-specific |
|---|---|
| Corpus, ingestion, index recipes | Graph topology (nodes, edges, loops) |
| Providers and LLM construction | Prompts beyond the shared generate prompt |
| Retriever building blocks | Which retrievers and transformers are composed |
| Generation prompt and context formatting (shared, moved out of `basic_rag`) | Decision logic (grading, routing, reflection) |
| Evaluation, triage, summary, resume, manifest | Extra state recorded via `record_keys` |
| Tracing callback | Experiment-specific settings section |

A `retrieve()`/`generate()` interface is **not** recommended. CRAG, Self-RAG and agentic RAG interleave retrieval and generation in loops, so a fixed two-method interface would force them into the wrong shape.

### 4.4 Retrieval composition boundaries

| Capability | Composition | Reuse (installed?) |
|---|---|---|
| Dense | `QdrantVectorStore.as_retriever` | ✅ in use |
| BM25 / sparse | `QdrantVectorStore(retrieval_mode=SPARSE, sparse_embedding=FastEmbedSparse("Qdrant/bm25"))` | ✅ installed |
| Hybrid + RRF | `retrieval_mode=HYBRID` (Qdrant server-side fusion, `FusionQuery`) | ✅ installed |
| Rerank | Wrap any retriever: retrieve top N → `fastembed` `TextCrossEncoder` (e.g. `Xenova/ms-marco-MiniLM-L-6-v2`, `BAAI/bge-reranker-base`) → top K | ✅ installed |
| Multi-query / decomposition | A graph node fanning out with `Send` (Phase 3.1) | ✅ built |
| HyDE | A graph node: LLM writes a hypothetical answer → embed → dense search | Prompt only; no dependency |
| Parent/child | Index small chunks with a `parent_id`, return the parent chunk | Docling chunk metadata + a Qdrant payload; reference: agentic-rag-for-dummies (MIT) |
| Contextual retrieval | An ingestion-time variant (LLM-written chunk context) → a separate index recipe | Ingestion change; no new dependency |

**Rule:** transformations of the *query* live in graph nodes. Transformations of the *ranked list* (rerank, fusion) live in retriever wrappers. Transformations of the *index* (sparse, parent/child, contextual) live in ingestion recipes, each with its own collection and manifest.

### 4.5 Benchmark architecture
- **Needed:**
  - a `compare` runner that reads every `results/*/` directory, picks the latest *complete* run per experiment, and pairs items scored in both runs against the control;
  - output as a Markdown table plus JSON;
  - **NOT RUN** for experiments with no complete run.
- **`benchmark --all`** would then mean: for each experiment config, run or resume it, then call `compare`. It is cheap to orchestrate, but limited by judge capacity (section 2, last row).
- **Current honest table:**

| Experiment | Recall@5 | MRR | Faithfulness | Correctness | Latency p50 | Cost |
|---|---:|---:|---:|---:|---:|---:|
| Basic RAG (baseline) | NOT MEASURED (no qrels) | NOT MEASURED | 0.847 | 0.724 | 6.92 s | null |
| Multi-query / decomposition (3.1) | NOT MEASURED | NOT MEASURED | judging in progress | judging in progress | — | null |
| Hybrid, Reranking, Query rewrite, CRAG, Adaptive, Self-RAG, Agentic, GraphRAG, Multi-agent | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

### 4.6 Fair experiment design

| Must stay identical (controlled variables) | How it is enforced today |
|---|---|
| Corpus | MANIFEST sha256 check at ingestion and evaluation; corpus hash in the manifest |
| Questions and golden answers | Dataset sha256 in the manifest; resume refuses a changed dataset |
| Evaluation metrics and judge | Part of the config fingerprint; a test pins the baseline fingerprint |
| Embedding model, chunking, index | Collection metadata guard (`open_store` refuses a mismatch) |
| Generator LLM and prompt | In the config; 3.1 reuses the generate node and prompt (tested byte-identical) |
| Top-K | In the config; a test asserts experiment configs differ only where documented |
| Environment | Package versions, Python, platform and git SHA in the manifest |

**Required architectural dependencies (not controlled variables, but documented per experiment):**

| Experiment | Extra dependency |
|---|---|
| Hybrid | Sparse index |
| Reranking | Cross-encoder model |
| Decomposition, query rewrite, HyDE | An extra LLM call (same model) |
| CRAG | A grader LLM call (+ web search, which would break the closed corpus, so exclude it or document it) |
| GraphRAG | Graph-construction LLM calls + a graph store |
| Multi-agent | Several agents (more LLM calls) |

Each must state its *added* LLM calls and tokens, which the harness already measures.

## 5. Experiment readiness

| # | Experiment | Ready? | Existing capability | Missing capability | Reuse candidate (licence) | Effort |
|---|---|---|---|---|---|---|
| 01 | Basic RAG | ✅ done | Graph, index, full baseline 42/42 | IR metrics | — | — |
| 02 | Hybrid RAG | 🟡 | Qdrant, langchain-qdrant `RetrievalMode.HYBRID`, `FastEmbedSparse("Qdrant/bm25")` installed | Sparse-enabled index recipe; retriever settings for mode | langchain-qdrant (MIT), Qdrant (Apache-2.0), FastEmbed (Apache-2.0) | S |
| 03 | Reranking | 🟡 | Retriever factory | Rerank wrapper (top N → cross-encoder → top K) | fastembed `TextCrossEncoder` (Apache-2.0, installed); `rerankers` 0.10.0 (Apache-2.0) | S |
| 04 | Query rewrite | 🟡 | Structured-output node pattern (3.1) | One rewrite node | LangGraph examples (MIT) | S |
| 05 | Multi-query | ✅ built (3.1) | `decompose_rag`, configs, tests | Judging in progress | agentic-rag-for-dummies (MIT, adapted) | — |
| 06 | Corrective RAG | 🟡 | Graph and harness; abstention metric | Grader node, conditional loop; web search excluded (closed corpus) | LangGraph `langgraph_crag` example (MIT) | M |
| 07 | Adaptive RAG | 🟡 | Same | Query-complexity router → strategy branches (reuses 01/02/05 retrievers) | LangGraph `langgraph_adaptive_rag` example (MIT) | M |
| 08 | Self-RAG | 🟡 | Same | Relevance, grounding and usefulness graders; loops with an iteration budget | LangGraph `langgraph_self_rag` example (MIT) | M |
| 09 | Agentic RAG | 🟡 | Tool-callable retriever possible | Agent with a retriever tool, tool-call loop | LangGraph `langgraph_agentic_rag` example (MIT); agentic-rag-for-dummies (MIT) | M |
| 10 | GraphRAG | 🔴 | Corpus, harness | Entity/relation extraction, graph store, graph retrieval | microsoft `graphrag` 3.3.0 (MIT) or `lightrag-hku` 1.5.7 (MIT); large LLM indexing cost | L |
| 11 | Multi-agent RAG | 🔴 | LangGraph | Supervisor and agents; evaluation of agent traces | `langgraph-supervisor` 0.0.31 (MIT) | M–L |

Effort: S ≈ under a day, M ≈ 1–3 days, L ≈ a week or more (excluding judge time).

**Cross-cutting prerequisites, in priority order:**

1. **qrels + IR metrics** (ranx) and score/rank recording. Without these, hybrid, rerank and multi-query cannot be compared on retrieval, which is their main claim.
2. **A judge capacity decision.** Free Groq gives about 5 days per experiment.
3. **The `compare` runner** with paired comparison and NOT RUN reporting.
4. **Langfuse server tracing** (reuse) for the multi-step graphs (06–11).
5. Move shared generation helpers out of `basic_rag.py`, and add a base-config `extends:` so experiment configs are diffs.

## 6. What should NOT change

- **The experiment contract** (`build_graph` → runnable; `answer` + `documents`).
- **Results layout and resume.**
- **The baseline's import path and config.** Moving `graphs/basic_rag.py` would break reproduction of the control run; if it moves, keep a shim.
- **No provider fallback in experiments.** It would break control.
- **No custom vector DB, BM25, reranker, tracing or evaluation framework.** All are available, installed or reusable (sections 3 and 4.4).
