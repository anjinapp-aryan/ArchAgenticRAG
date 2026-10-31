# Experiment 03: Reranking — Reuse Audit and Design Review

Status: audit and design only, 2026-10-29. Nothing is implemented. No production code, graph, collection, config or result changed. No model was downloaded except the re-download of the already-used `Qdrant/bm25` cache (section 14). No LLM or judge was called.

## 1. Executive summary

**Proposal: hybrid retrieval to a 20-chunk candidate pool, then a local cross-encoder reranks it to the final 4.** Everything needed is already installed or one small package away:
- `langchain-qdrant` returns a 20-deep hybrid pool when `k=20` is passed, with no library change;
- `fastembed` 0.8.1, already used for the embeddings and BM25, ships `TextCrossEncoder` with license-clean ONNX rerankers that run on CPU;
- `langchain-core` provides the `BaseDocumentCompressor` interface;
- `langchain-classic` provides `ContextualCompressionRetriever`, which composes them below the graph.

**Measured, read-only, on the existing hybrid index** (31 answerable questions):

| Candidate depth K | Chunk Recall@K | Doc Recall@K | Questions with no relevant chunk in pool |
|---:|---:|---:|---:|
| 4 | 0.680 | 0.952 | 4 |
| 10 | 0.739 | 0.984 | 3 |
| **20** | **0.874** | **1.000** | **1** |
| 30 | 0.874 | 1.000 | 1 |
| 50 | 0.901 | 1.000 | 1 |

A 20-chunk pool holds the evidence for 30 of 31 questions, so a reranker has room to lift final Recall@4 from 0.680 up to a ceiling of 0.874. K = 20 sits at the plateau.

**New risk found during the audit: hybrid retrieval is not deterministic.**
- Qdrant's RRF produces exact score ties (for example 0.5, 0.5, 0.5), and their order is arbitrary.
- Repeating the Experiment 02 retrieval 10 times gives chunk Recall@4 0.648–0.680 (mean 0.674) and MRR 0.699–0.772 (mean 0.748).
- Every repeat stays above the baseline (0.589 / 0.640), so Experiment 02's WIN direction holds. The recorded run sits at the top of the range.
- Dense retrieval (01) is deterministic: 0 of 42 differ.

**Decision: GO WITH CONDITIONS** (section 20).

## 2. Current architecture

```text
eval/configs/exp02-hybrid-bm25.yaml ── system ──► archagenticrag.graphs.basic_rag:build_graph(system)
                                                     │  parse_settings → RAGSettings
                                                     │  open_store(client, settings, embeddings, sparse)   rag/vector_store.py
                                                     │      QdrantVectorStore(retrieval_mode=HYBRID, sparse_embedding=FastEmbedSparse("Qdrant/bm25"))
                                                     │  make_retriever(store, settings)                     graphs/basic_rag.py
                                                     │      store.as_retriever("similarity", {"k": top_k}).with_config(retrieval_method="hybrid(dense+bm25,rrf)")
                                                     ▼
                                       START → retrieve → generate → END
```

- **Experiment contract:** `build_graph(system) → graph`. Experiments 01 and 02 use the same factory; only `system.retrieval` differs.
- **Provider fallback:** `system.provider_strategy` reaches only `providers.chat_model` (generator) and `judge.provider_strategy` reaches only the Ragas client. Retrieval never touches it. Experiment 03 does not set it.
- **Reranker slot:** `SystemConfig.reranker: ModelRef | None` already exists in the evaluation config. The baseline sets it to `null`, so it is already part of every fingerprint. `RAGSettings.reranker` is currently typed `None`.

## 3. Existing retrieval flow

| # | Question | Current answer |
|---|---|---|
| 1 | How does 02 do hybrid? | `QdrantVectorStore.similarity_search_with_score` in HYBRID mode: one `query_points` call with two `Prefetch` branches (dense `using=""`, BM25 `using="langchain-sparse"`), fused by `FusionQuery(Fusion.RRF)` |
| 2 | Where is candidate k? | `system.retrieval.top_k`. `RetrievalSettings.search_kwargs()` passes it as `k` |
| 3 | Is langchain-qdrant limited to 4? | No. Both prefetch limits and the fused limit equal `k`. `k=20` gives 20 fused results from two 20-deep branches. Prefetch depth cannot differ from the returned count, which is acceptable here (section 7). |
| 4 | Document representation | LangChain `Document`: `page_content`, `metadata.{doc_id, chunk_id, section, …, _id, _collection_name}` |
| 5 | Instrumentation | `evaluation/retrieval_trace.RetrievalRecorder`, a retriever callback. It records every retriever call: query, method (`retrieval_method` metadata), latency, and results (rank, doc_id, chunk_id, score from `relevance_score`/`score` metadata or `null`). `final_results` describes the graph's context list, taking method/score from the *outermost* call that returned each chunk. |
| 6 | Labels | `eval/datasets/peps-v1/qrels/<collection>.json`: evidence-bearing `chunk_id`s (binary) and `source_documents` |
| 7 | Metrics | `evaluation/ranking.run_ranking` takes each item's `retrieval_results` chunk order (or context-hash mapping for older runs) and computes ir_measures R@K, RR and nDCG@K, chunk and doc level |
| 8–9 | Graph | `basic_rag.build_graph`; the retriever is built in `make_retriever` and the graph only calls `retriever.invoke` |
| 10 | 02 config | baseline YAML plus `retrieval.{mode: hybrid, sparse, fusion}` and its own collection (diff pinned by a test) |
| 11 | Manifests | `config_fingerprint`, the full config, `target_metadata.index` (collection metadata incl. `retrieval_mode`, `sparse`), and the registry entry in `eval/experiments.yaml` |
| 12 | Provider isolation | see section 2 |
| 13 | Tests | `tests/rag/test_hybrid_rag.py` (in-memory Qdrant, fake sparse model, `query_points` spy) and `tests/integration/test_local_stack.py` (real Qdrant/FastEmbed) |
| 14 | Reranking installed? | Yes: `fastembed.rerank.cross_encoder.TextCrossEncoder` (`rerank(query, documents) → scores`). There is no LangChain wrapper for it in the installed packages. |

## 4. Reuse audit

| Capability | Option | Version | License (verified from) | Installed | Decision |
|---|---|---|---|---|---|
| Cross-encoder inference | **fastembed `TextCrossEncoder`** (ONNX Runtime) | 0.8.1 | Apache-2.0 (package metadata) | yes | **REUSE**: same runtime and cache as the existing embeddings |
| Rerank as a LangChain component | `langchain_core.documents.BaseDocumentCompressor` | langchain-core 1.6.6 | MIT | yes | **ADAPT**: about 25 lines that call `TextCrossEncoder.rerank`, store the score as `metadata["relevance_score"]` (which the Phase 3.0 trace already reads), and keep the top `final_k` |
| Retriever = base retriever + compressor | `ContextualCompressionRetriever` | langchain-classic 1.0.8 | MIT (PyPI classifier) | **no** (LangChain 1.x moved it out of `langchain`) | **REUSE**. It adds `langchain-classic`, `langchain-text-splitters` and `async-timeout`; SQLAlchemy and langsmith are already installed. |
| Candidate retrieval (top 20) | existing `QdrantVectorStore` HYBRID with `k=20` | langchain-qdrant 1.1.0, Qdrant 1.19.1 | MIT / Apache-2.0 | yes | **REUSE**, unchanged |
| Ranking metrics | Phase 3.0 `ranking.py` (ir-measures 0.4.3) | — | Apache-2.0 | yes | **REUSE**; adds a candidate-stage level |
| Evaluation / benchmark | Phase 3.0 runner, `--defer-judge`, `benchmark.py` | — | project | yes | **REUSE** |
| Tracing | Langfuse LangChain callback (opt-in) | 4.16.0 | MIT | yes | **REUSE**: compressor and base retriever calls appear as nested spans |

## 5. Reranker candidates

| Candidate | License | Installed | Dependencies | CPU | GPU | Fit |
|---|---|---|---|---|---|---|
| **fastembed `TextCrossEncoder`** | Apache-2.0 | yes | none new | yes (onnxruntime 1.30.0, CPU provider) | needs `fastembed-gpu` / `onnxruntime-gpu` (replaces the CPU runtime for the whole environment) | **Best**: already the project's inference runtime |
| LangChain `FlashrankRerank` + `flashrank` | Apache-2.0 (flashrank 0.2.10) | wrapper yes, `flashrank` no | flashrank (its deps are already installed) | yes (ONNX) | no | Good, but a second ONNX model manager and model host (`prithivida/flashrank`) for the same models fastembed already serves |
| `sentence-transformers` CrossEncoder (+ classic `CrossEncoderReranker`) | Apache-2.0 | no | **torch** (≥ 2 GB with CUDA), transformers ≥ 5, scikit-learn | yes | yes | Rejected: heavy; `CrossEncoderReranker` drops scores (nothing for the trace) |
| FlagEmbedding (BGE) | not declared in PyPI metadata | no | torch, datasets, accelerate, peft, sentence-transformers, ir-datasets | yes | yes | **Rejected**: unclear package license, very heavy |
| `rerankers` (AnswerDotAI) | Apache-2.0 | no | backend-dependent | yes | yes | Rejected: a second abstraction over the same backends |
| Jina / Cohere / Voyage / DashScope / Volcengine API rerankers (`langchain_community`) | provider terms | wrappers yes | network, key | — | — | **Rejected**: paid or external APIs |
| `InfinityRerank`, `OpenVINOReranker` | MIT / Apache | wrappers yes | separate server / OpenVINO | — | — | Not needed locally; Infinity is a production option (section 16) |

## 6. Model candidates

All are in fastembed 0.8.1's `TextCrossEncoder.list_supported_models()`. Licenses and configs were checked on the Hugging Face model cards and `config.json`.

| Model | License (source) | Params | Download | Max tokens | Fit |
|---|---|---:|---:|---:|---|
| **BAAI/bge-reranker-base** | **MIT** (model card) | 278 M (XLM-R base) | 1.04 GB | 512 | **Primary**: widely used passage reranker, clean license, strongest of the license-clean options; slowest on CPU |
| jinaai/jina-reranker-v1-tiny-en | Apache-2.0 (model card) | 33 M (4 layers) | 0.13 GB | 8,192 | **Fallback** if bge is too slow: fast, no truncation; smaller and weaker |
| jinaai/jina-reranker-v1-turbo-en | Apache-2.0 (model card) | ~38 M | 0.15 GB | 8,192 | alternative to tiny |
| Xenova/ms-marco-MiniLM-L-6-v2 / L-12-v2 | **No license on the ONNX repo's card**. The base `cross-encoder/ms-marco-MiniLM-L-6-v2` is Apache-2.0. | 23 M / 33 M | 0.08 / 0.12 GB | 512 | **Not selected**: redistribution license not stated by the repository fastembed downloads from |
| jinaai/jina-reranker-v2-base-multilingual | **CC-BY-NC-4.0** | ~278 M | 1.11 GB | 1,024 | **Rejected**: non-commercial |

**Chunk fit for 512-token models**, measured with the cached BERT-uncased tokenizer; XLM-R counts differ slightly:
- chunks: median 201 tokens, p95 475, max 493;
- questions: median 18.5 tokens, max 44;
- with the median question, **2 of 455** chunks exceed the 512 window; with the longest question, 36 do.

When a pair exceeds the window, the *end* of the chunk is truncated. The impact is small and is recorded as a limitation, not a blocker.

## 7. Candidate retrieval design

- **Settings.** New retrieval setting `candidate_k: 20`, allowed only together with a reranker. `top_k: 4` stays the final count.
- **Retriever.** The candidate retriever is the existing hybrid retriever with `k = candidate_k`. langchain-qdrant then prefetches 20 per branch and RRF-fuses to 20.
- **No library change, no new collection.** Experiment 03 reads `peps_v1_bge_small_docling_480_hybrid_bm25`, the same index and qrels as Experiment 02.
- **Depth confound.** Deeper prefetch alone changes the fused order. The top 4 of the 20-pool without reranking scores R@4 0.664 and MRR 0.737, vs 0.680 / 0.772 for the 4-deep hybrid in the same probe. The candidate-stage trace makes this measurable for free (section 11, diagnostic).
- **Why 20.** Candidate recall plateaus between 20 and 30 (0.874 at both). 50 adds +0.027 at 2.5× the reranking cost. 10 leaves 3 questions without evidence. Retrieval latency is flat (p50 about 10–12 ms from K = 4 to 50).

## 8. Reranking design

```text
graph.retrieve ──► ContextualCompressionRetriever                     metadata: retrieval_method="rerank(bge-reranker-base)", retrieval_stage="final"
                      ├─ base_retriever: hybrid store.as_retriever(k=20)  metadata: retrieval_method="hybrid(dense+bm25,rrf)", retrieval_stage="candidate"
                      └─ base_compressor: FastEmbedCrossEncoderRerank(model, top_n=4)
                              TextCrossEncoder.rerank(query, [doc.page_content …]) → scores
                              sort by (score desc, candidate rank asc)   # deterministic tie-break
                              keep 4, metadata["relevance_score"] = score
               ──► 4 Documents ──► generate (unchanged)
```

- **Where it lives.** `make_retriever` in `basic_rag.py` builds this when `settings.reranker` is set. The graph, nodes, prompt and generator are untouched, and `build_graph(system)` is preserved.
- **Code size.** The only new code is the compressor adapter (in `rag/`, about 25 lines) and settings validation.
- **Model loading.** The model loads once per graph build (lazy), from a stable cache path (condition C5).

## 9. Instrumentation changes

What already works with no change:
- the base retriever call (20 results, ranks, method `hybrid…`, score `null`);
- the outer call (4 results, `relevance_score`);
- `final_results` taking method and score from the outer call.

Minimum additions, all backward compatible (Phase 3.0 records stay valid):

| Field | Where | How |
|---|---|---|
| `retrieval_stage` (`candidate` / `final` / null) | each `retrieval_calls[]` entry | read from the retriever's `metadata["retrieval_stage"]`, like `retrieval_method` |
| `candidate_rank`, `candidate_method` | each `retrieval_results[]` entry | looked up from the candidate-stage call for that chunk_id; `null` when there is no candidate stage |
| `score_key = "relevance_score"` | already exists | the reranker score; the candidate score stays `null` because the retriever drops RRF scores |

## 10. Metric design

Two separate questions, reported side by side by `benchmark.py`:

| Layer | Source | Metrics | Answers |
|---|---|---|---|
| **Candidate** | the `retrieval_stage == "candidate"` call per item | Recall@20 (also @10), doc Recall@20 | Did hybrid retrieval put the evidence anywhere in the pool? (the ceiling for reranking) |
| **Candidate-truncated** (diagnostic) | first 4 of the candidate list | Recall@4, MRR, nDCG@4 | What does depth alone do, without reranking? |
| **Final** | `retrieval_results` (as today) | Recall@4, MRR, nDCG@4, chunk and doc | Did reranking put the evidence in the 4 chunks the generator sees? |
| **Reranker lift** | final − candidate-truncated, per item W/T/L | Δ Recall@4, Δ MRR | Effect attributable to the reranker |
| **Reranker efficiency** | final R@4 ÷ candidate R@20 | ratio | How much of the reachable evidence was surfaced |

A final miss whose evidence was absent from the pool counts as a **candidate failure**, not a reranker failure. Per-item tables keep the two apart.

## 11. Experiment matrix

| Experiment | Retrieval | Candidate K | Final K | Reranker | Status |
|---|---|---:|---:|---|---|
| 01 | Dense | 4 | 4 | — | official (frozen) |
| 02 | Hybrid (RRF) | 4 | 4 | — | official |
| 03 | Hybrid (RRF) | 20 | 4 | bge-reranker-base (cross-encoder, CPU) | official, proposed |
| 03-D | Hybrid (RRF), top 4 of the 20-pool | 20 | 4 | — | **diagnostic only**: read from 03's candidate trace, no extra run, not registered as an experiment |

## 12. Controlled variables

**Identical to 02:**
- corpus and chunking (same collection, same 455 chunks);
- embedding model, BM25 model, RRF fusion;
- dataset and qrels;
- generator `groq / openai/gpt-oss-120b`, temperature 0, prompt;
- judge config and metrics list;
- provider strategy (single, unset).

**Changed:** `retrieval.candidate_k` (new, 20) and `system.reranker` (`null` → `{provider: local, model: BAAI/bge-reranker-base}`). A config-diff test pins exactly these two changes, plus `run_name`.

**Unavoidably coupled:** branch prefetch depth follows `candidate_k`, which the 03-D diagnostic quantifies.

## 13. Test plan

**Unit tests (offline, fake cross-encoder returning fixed scores)**
- The candidate retriever returns more than `final_k` (20 with in-memory Qdrant over ≥ 20 chunks).
- The compressor receives exactly the candidate documents, in candidate order.
- Ordering follows the mocked scores, ties broken by candidate rank, so the result is deterministic.
- Output length is exactly `final_k` (and all candidates when there are fewer).
- Candidate metadata (`doc_id`, `chunk_id`) is preserved and `relevance_score` is set.
- No duplicate chunk_ids.
- The trace has two calls with stages `candidate` and `final`; `candidate_rank` is filled; ranking metrics work at both stages.
- Settings: `candidate_k` without a reranker is rejected; `candidate_k < top_k` is rejected; a reranker without hybrid is allowed but not part of 03.
- The config diff against 02 is exactly the documented one; baseline and 02 fingerprints are unchanged.

**Integration (real Qdrant, real hybrid, real reranker, small model in CI)**
- A top-20 candidate call, then a top-4 final call, on the real index.
- Scores are present and `retrieval_stage` is recorded.
- The model loads from the configured cache.

**Regression:** offline 232/232, integration 17/17 and live 4/4 must stay green. No full 42-question live run during implementation.

## 14. Performance and resource estimate

| Item | Value | Basis |
|---|---|---|
| Candidate retrieval, K = 20 | p50 ≈ 10.6 ms | **measured** (31 questions, local Qdrant) |
| bge-reranker-base download | 1.04 GB, once | fastembed metadata |
| bge-reranker-base CPU rerank, 20 pairs × ~220 tokens | **estimated 1–3 s / question** | 278 M-param encoder, ~4,400 tokens per question; **not measured** (measuring needs the 1 GB download, outside this phase) |
| jina-reranker-v1-tiny CPU, same pairs | **estimated ≤ 0.3 s / question** | 33 M params, 4 layers; **not measured** |
| Memory | ~1.1–1.5 GB RAM (bge) / ~0.2 GB (jina tiny) | model size plus ONNX runtime overhead; estimate |
| GPU (RTX 5060 Ti 16 GB present) | **not used** | onnxruntime here has only the CPU provider. `onnxruntime-gpu` would replace it for the embeddings too and could shift embedding numerics, so it is a baseline-reproducibility risk. |
| Cold start | one model load per process (seconds) and a one-time download | fastembed lazy load |

**Cache finding.** fastembed's default cache is `%TEMP%\fastembed_cache`. It was emptied between sessions: `Qdrant/bm25` had to be re-downloaded for this audit (the same model and version, nothing new). A 1 GB reranker in `%TEMP%` would be re-downloaded the same way. Set `FASTEMBED_CACHE_PATH` (honoured by fastembed) to a persistent folder (condition C5).

## 15. Licensing and dependency risk

| Component | License | Commercial use | Current status | Decision |
|---|---|---|---|---|
| fastembed 0.8.1 | Apache-2.0 | yes | installed | use |
| onnxruntime 1.30.0 | MIT | yes | installed | use |
| langchain-core 1.6.6 | MIT | yes | installed | use |
| langchain-classic 1.0.8 (+ text-splitters, async-timeout) | MIT | yes | not installed | add (condition C4) |
| BAAI/bge-reranker-base | MIT (model card) | yes | not downloaded | **primary** |
| jinaai/jina-reranker-v1-tiny-en | Apache-2.0 (model card) | yes | not downloaded | fallback |
| Xenova/ms-marco-MiniLM-L-*-v2 | not stated on the ONNX repo (base Apache-2.0) | unclear | — | **reject** for implementation |
| jinaai/jina-reranker-v2-base-multilingual | CC-BY-NC-4.0 | **no** | — | reject |
| FlagEmbedding | not declared in package metadata | unclear | — | reject |

## 16. Production considerations

- **Status of this design:** development and benchmark use. It is suitable for a single long-lived process (a local server or container), where the 1 GB model loads once.
- **Not suitable as-is for serverless (Vercel functions):** the model size and ONNX runtime exceed typical function bundle and memory limits, and every cold start would reload the model.
- **Production path, not designed here:** a separate reranking service behind the same compressor interface. Options are a self-hosted Infinity server (LangChain `InfinityRerank` already exists) or Qdrant's own inference features. A small model (jina tiny) is the fallback where latency matters.

## 17. Alternatives rejected

| Alternative | Reason |
|---|---|
| Reranking only the 4 hybrid chunks | Cannot change Recall@4, only order; does not test reranking |
| A custom `Reranker` class or ranking framework | `BaseDocumentCompressor` + `ContextualCompressionRetriever` already define query + candidates → ranked documents |
| sentence-transformers / FlagEmbedding | torch dependency (GB-scale); FlagEmbedding license undeclared; `CrossEncoderReranker` discards scores |
| flashrank | Duplicates fastembed's model management for the same model family |
| `rerankers` library | Extra abstraction layer over backends we already have |
| API rerankers (Cohere, Jina, Voyage, …) | Paid or external; violates the local, no-paid-API rule |
| Deeper prefetch with final fusion limit 20 via raw `qdrant-client` | Would bypass langchain-qdrant for no measured benefit (candidate recall already plateaus at 20) |
| LLM-as-reranker (RankLLM, rank_zephyr) | Spends generator quota and changes model family; a different experiment |
| K = 50 | +0.027 candidate recall for 2.5× the reranking time |
| GPU via onnxruntime-gpu | Replaces the CPU runtime used by the frozen embeddings; reproducibility risk |

## 18. Implementation plan (not executed)

1. Set `FASTEMBED_CACHE_PATH` to a persistent directory (documented in `.env.example` and README). Download bge-reranker-base. **Measure** its CPU latency on 20 real candidates. If p50 is over 3 s, switch to jina-reranker-v1-tiny-en **before** any quality measurement, and record why.
2. Settings: `RAGSettings.reranker: RerankerSettings | None` (`provider: local`, `model`) and `RetrievalSettings.candidate_k` (only with a reranker; ≥ `top_k`). Baseline and 02 fingerprints unchanged (test).
3. `rag/rerank.py`: a fastembed cross-encoder `BaseDocumentCompressor` adapter (score into `relevance_score`, deterministic tie-break).
4. Add `langchain-classic` to the eval extra; `make_retriever` wraps it in `ContextualCompressionRetriever` when a reranker is set, labelling the base and outer retrievers with `retrieval_method` and `retrieval_stage`. Check that base-retriever callbacks nest (child run manager).
5. `retrieval_trace`: record `retrieval_stage`; add `candidate_rank` and `candidate_method` to final results.
6. `ranking.py` and `benchmark.py`: candidate-stage metrics (R@10/20), the 03-D diagnostic and reranker lift; `vs_baseline` against both 01 and 02.
7. Config `eval/configs/exp03-hybrid-rerank.yaml` (02 + `candidate_k: 20` + reranker) and a registry entry.
8. Unit, integration and regression tests (section 13).
9. Tier 1: `run_eval.py … --defer-judge` (42 questions, no judge), then `benchmark.py`. Write `docs/EXPERIMENT-03-RERANKING.md` with candidate, final, lift, category and per-item tables, plus a WIN / MIXED / NO IMPROVEMENT / REGRESSION decision.
10. Tier 2 (Ragas), only after the retrieval result is accepted; same judge, single provider unless a separate, labelled provider strategy is approved.

## 19. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **RRF ties make hybrid candidate order non-deterministic.** 9 of 31 questions' top-20 *sets* vary across repeats, though candidate Recall@20 stayed 0.874 in all 10. | Small run-to-run variance in 03; 02's recorded run is one draw (R@4 0.648–0.680) | Reranker reorders the set deterministically; record the candidate set per item; compare 03 with 02's repeat mean as well as its recorded run; report the variance |
| bge-reranker-base too slow on CPU | Long Tier 1 runs | Pre-registered switch to jina tiny (step 1), decided on latency, not on quality |
| 512-token truncation | Tail of ≤ 36 chunks cut for long questions | Recorded limitation; jina (8K) avoids it |
| Depth confound | Gain or loss attributed to the wrong cause | 03-D diagnostic plus the lift metric |
| Small sample (n = 31) | Results directional, not significant | Per-item W/T/L, sign test, categories |
| Retrieval win ≠ answer win | Over-claiming | Ragas tier kept separate. Recall@4 / MRR / nDCG@4 gains do **not** imply better faithfulness, correctness or relevancy. |
| langchain-classic callback nesting differs from expectation | Missing candidate trace | Verified by a unit test before the run (step 4) |

## 20. GO / NO-GO

**GO WITH CONDITIONS.**

- **Why GO:** a mature, license-clean reranker exists in the installed runtime. Candidate depth increases with no library change. The final top 4 stays fixed. Instrumentation extends compatibly. Metrics can separate candidate retrieval from reranking. The baseline and 02 stay untouched, with no architectural rewrite.

**Conditions**
- **C1 — Tie non-determinism:** acknowledged in the 03 design. Record candidate sets, and report 02 as a range (or repeat mean) next to its recorded run. Whether to annotate the Experiment 02 report with this finding is **your decision**; it was not edited here.
- **C2 — Model:** bge-reranker-base (MIT) as pre-registered primary; jina-reranker-v1-tiny-en (Apache-2.0) only if the step-1 latency check fails; MiniLM ONNX ports not used (license not stated on the downloaded repo).
- **C3 — CPU only:** no `onnxruntime-gpu`.
- **C4 — langchain-classic:** add it as the single new dependency (MIT, 3 small packages) for `ContextualCompressionRetriever`, after confirming its callback nesting.
- **C5 — Model cache:** a persistent `FASTEMBED_CACHE_PATH` before any model download.
