# Phase 3.0: RAG Experiment Lab Infrastructure

Status: implemented, 2026-10-27. Infrastructure only. No retrieval or generation technique was added or changed.

## 1. Why Phase 3.0 exists

The architecture audit (`docs/ARCHITECTURE-AUDIT.md`) found that the code structure was not the bottleneck. The experiment infrastructure was:

- **No ranking metrics.** Retrieval quality was judged only through Ragas context metrics, which need the LLM judge, and two coarse checks. There were no chunk-level relevance labels.
- **Rank data not exposed.** Retrieved rank, score and method were not recorded in a form that ranking evaluation could use.
- **No comparison view.** There was no comparison across runs and no explicit NOT RUN state.
- **Judge-bound evaluation.** Every evaluation needed the free-tier LLM judge, which allows about 9 questions a day.

Phase 3.0 makes "did retrieval improve?" answerable without a judge, in minutes. "Did the answer improve?" remains a separate question for Ragas.

## 2. Current architecture (unchanged)

The graph is still the unit of an experiment: `build_graph(system) -> compiled LangGraph graph`, with `question` in and `answer` plus `documents` out. No `RAGExperiment` class was introduced, so CRAG, Self-RAG, Adaptive and agentic graphs can use loops and conditional edges freely.

```text
eval/configs/<experiment>.yaml ─┐
                                ▼
eval/runners/run_eval.py ──► evaluation.runner ──► evaluation.target.run_target ──► graph.invoke
        [--defer-judge]          │                     callbacks: tokens, LLM calls, latency,
                                 │                     RetrievalRecorder (NEW), Langfuse handler (NEW, opt-in)
                                 ▼
                        eval/results/<run_id>/  manifest.json, config.yaml, items.jsonl, summary.json
                                 │
eval/runners/resume_eval.py ─────┤  (judges pending items, one day's quota at a time)
                                 ▼
eval/runners/benchmark.py --all ──► evaluation.benchmark (NEW)
        reads: eval/experiments.yaml (NEW), eval/datasets/<ds>/qrels/<collection>.json (NEW),
               eval/pricing.yaml (NEW)
        layer 1: evaluation.ranking (NEW) — Recall@K, MRR, nDCG via ir_measures
        layer 2: Ragas metrics already stored per item
```

**Baseline protection**
- `archagenticrag.graphs.basic_rag:build_graph`, the baseline config and the baseline fingerprint `63bf3b5f990cc9e5` are unchanged; the existing pinned test still passes.
- No result in `eval/results` was modified; the benchmark only reads.
- The new per-item fields (`retrieval_results`, `retrieval_calls`) and manifest field (`judge_deferred`) are not part of the config, so they cannot change any fingerprint.

## 3. Retrieval instrumentation

`src/archagenticrag/evaluation/retrieval_trace.py`. A LangChain callback handler (`RetrievalRecorder`) is attached to every target invocation. Because it listens to retriever callbacks, it works for any graph without changing it.

| Item field | Content |
|---|---|
| `retrieval_results` | The graph's **final** context list, in the order the generator saw it: `rank` (1-based), `doc_id`, `chunk_id`, `score`, `score_key`, `method` |
| `retrieval_calls` | **Every** retriever call: `query`, `method`, `latency_s`, `results` (same shape), `error`, run ids. Multi-query fan-out, a reranker wrapping a base retriever, and CRAG retries each appear as separate calls. |

- **Score.** Recorded only when the retriever puts one in document metadata (`relevance_score` from LangChain compressors/rerankers, or `score`). LangChain's `VectorStoreRetriever` similarity search does not, so for the baseline `score` is `null`, not estimated. The integration test asserts this.
- **Method.** The retriever's own `retrieval_method` metadata, which an experiment sets with `retriever.with_config(metadata={"retrieval_method": "hybrid"})`. Otherwise it is the class and vector store LangChain reports, e.g. `VectorStoreRetriever(QdrantVectorStore)`.
- **Latency.** Per call, plus the existing per-item `retrieval_latency_s`.
- **Experiment id.** A run-level field (section 7), not repeated per chunk.

**Runs recorded before Phase 3.0** have no `retrieval_results`. Their context texts are mapped back to chunk ids by exact sha256 match against the qrels chunk catalog. For all four existing runs, 822 of 822 contexts matched.

## 4. Relevance labels

`src/archagenticrag/evaluation/relevance.py`, built by `eval/runners/build_qrels.py <config>`, stored in `eval/datasets/peps-v1/qrels/peps_v1_bge_small_docling_480.json`.

**Problem.** Golden evidence quotes are raw reStructuredText, e.g. ` ``NAME := expr`` ` or `` :pep:`484` ``. Chunks hold rendered text (docutils → HTML → Docling), which adds `*emphasis*`, spaces before punctuation after inline code, and `[[1]](#footnote-1)` links. A whitespace-normalised substring check (after removing the RST double backticks) matched only 58 of 80 quotes. The same weakness affects the Phase 2 `evidence_in_context` check (see PHASE-2-BASELINE-RESULTS §4).

**Deterministic rule (no LLM, no manual labels):**
1. Render the quote with **docutils**, the renderer the ingestion uses, and drop docutils' warning nodes.
2. Reduce quote and chunk text to their lower-case alphanumeric token sequence, after removing Docling footnote links.
3. A chunk is relevant (grade 1) to an item when it belongs to the evidence's **cited document** and contains the quote's token sequence.

**Result for the baseline chunking (455 chunks)**
- 80 of 80 evidence quotes are matched; `unmatched_evidence` is empty.
- 35 items are labelled: 31 answerable and 4 clarify. The 6 abstain items have no relevant chunks by design.
- 63 relevant chunks: 14 items have 1, 15 have 2, 5 have 3, and 1 has 4.
- Quotes that also occur in *other* documents are listed under `also_found_in` but not labelled relevant, because the golden set cites one document per quote. Three items have such copies: B01, D04 (header lines) and G06.
- Document-level labels are `source_documents`. They do not depend on the chunking.

**Integrity checks**
- Offline test: the committed file's dataset hash equals the current `golden.json`, and every evidence quote has at least one chunk.
- Integration test: a fresh chunking reproduces the catalog (chunk id → text hash) exactly. A read-only scroll of the baseline Qdrant collection must match it as well.

**Limits**
- Labels are binary and evidence-based. A chunk that paraphrases the answer without containing a gold quote counts as non-relevant.
- Qrels are tied to one chunking. An experiment with a new index (different chunking) needs its own file, built by the same script, and its chunk-level numbers are not comparable with the baseline's. Document-level metrics remain comparable.

## 5. Ranking metrics

`src/archagenticrag/evaluation/ranking.py`. The arithmetic is done by **ir_measures** on its pytrec_eval backend, i.e. the reference trec_eval implementation.

| Metric | Question it answers |
|---|---|
| Recall@K | Of the evidence-bearing chunks, what fraction is in the top K the generator saw? |
| MRR | How high is the first evidence-bearing chunk? (1 / rank of the first relevant chunk, 0 if none) |
| nDCG@K | How well are the relevant chunks ranked overall? Relevant chunks lower in the list count less. |

**Cutoffs.** The default cutoffs are K ∈ {1, 3, 4, 5, 8, 10}. 4 is the baseline `top_k` and 8 is the largest context list so far (B1, and the 3.1 cap). `--k` chooses the table columns; JSON output holds every cutoff.

**Conventions**
- **Ranked list.** The ranked list is the final context list in generator order, with duplicate chunks keeping their first rank. trec_eval sorts by score, so lists get strictly decreasing synthetic scores from their rank order.
- **Short lists.** Recall@8 for a 4-chunk list equals its Recall@4. That is intended: it measures what the system *delivered*.
- **Item set.** Headline means cover the 31 answerable items with qrels. Clarify items are excluded, because ranking is ill-defined for an ambiguous question.
- **Zero scores.** Items with no list score 0; a missing value is never silently skipped.
- **Paired comparison.** Items that any compared run failed on with a system error (provider quota errors) are excluded from the paired comparison, so a 429 is not scored as a retrieval miss. Unpaired (`all_items`) numbers are in the JSON.

## 6. Benchmark comparison

`python eval/runners/benchmark.py --all [--k 4 8] [--json out.json] [--markdown out.md]`

The comparison needs no model, judge, Qdrant or Langfuse, and never modifies a run.

**Run selection.** Runs map to experiments by `run_name` through `eval/experiments.yaml`. If several runs exist for one experiment, the latest is compared unless `pinned_run` is set, and the others are listed.

**Statuses**

| Status | Meaning |
|---|---|
| COMPLETE | Every item answered and judged, or the run is listed in `final_runs` (finalized with recorded gaps, like the baseline) |
| IN PROGRESS | Items pending: system errors or metrics without a value (judge quota, `--defer-judge`) |
| RETRIEVAL ONLY | Answers recorded; answer judging deliberately skipped (`answer_eval: skipped`) |
| FAILED | Run unreadable, or every item failed |
| NOT RUN | No run for the experiment. Shown as `—`, **never as 0** |

**Output on 2026-10-27** (current `eval/results`). Chunk-level ranking is paired over 26 items; B02, C05, E05, F02, F06 and G02 are excluded because a compared run hit a system error on them.

| Experiment | Status | Pass | Recall@4 | Recall@8 | MRR | nDCG@8 | Faithfulness | Correctness | Latency p50 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 01 Basic RAG | COMPLETE | 27/42 | 0.587 | 0.587 | 0.673 | 0.575 | 0.847 (n=34) | 0.724 (n=30) | 6.92 s |
| 02 Hybrid retrieval | NOT RUN | — | — | — | — | — | — | — | — |
| 03 Reranking | NOT RUN | — | — | — | — | — | — | — | — |
| 04 Query rewrite | NOT RUN | — | — | — | — | — | — | — | — |
| 05 Multi-query (query decomposition, Phase 3.1) | IN PROGRESS | 2/2 judged (40 pending) | 0.587 | 0.606 | 0.673 | 0.584 | 1.000 (n=2) | 1.000 (n=1) | 11.16 s |
| 06 CRAG | NOT RUN | — | — | — | — | — | — | — | — |
| 07 Adaptive RAG | NOT RUN | — | — | — | — | — | — | — | — |
| 08 Self-RAG | NOT RUN | — | — | — | — | — | — | — | — |
| 09 Agentic RAG | NOT RUN | — | — | — | — | — | — | — | — |
| 10 GraphRAG | NOT RUN | — | — | — | — | — | — | — | — |
| 11 Multi-agent RAG | NOT RUN | — | — | — | — | — | — | — | — |
| 05-B1 Control B1: Basic RAG, top_k 8 | IN PROGRESS | 1/1 judged (41 pending) | 0.587 | 0.663 | 0.679 | 0.604 | — | — | 16.37 s |
| 05-B2 Control B2: Basic RAG, MMR (fetch_k 20) | RETRIEVAL ONLY | — | 0.446 | 0.446 | 0.590 | 0.470 | — | — | 1.11 s |

**How to read it**
- The baseline row reproduces PHASE-2-BASELINE-RESULTS: 27/42 pass, faithfulness 0.847 (n=34), correctness 0.724 (n=30), latency p50 6.92 s.
- Phase 3.1's Ragas cells (n=1–2) are not comparable yet; judging continues through the daily resume.
- Document-level Recall@4 is 0.981 for all four runs on the paired set. Retrieval almost always reaches the right PEP; the gap is in reaching the evidence-bearing chunk.
- Latencies were measured on different days and under different provider load.

## 7. Experiment metadata contract

`benchmark.run_metadata` derives the contract from the run's own manifest and config, so it also covers runs recorded before Phase 3.0. Every compared row carries:

| Field | Source |
|---|---|
| `experiment_id`, `experiment_name`, `role` | registry entry (`experiment` or `control`) |
| `run_id`, `run_name`, `started_at` | manifest |
| `completed_at` | manifest `finished_at` or the last resume session's, only when COMPLETE / RETRIEVAL ONLY |
| `git_commit`, `git_dirty` | manifest `git` |
| `config_fingerprint`, `fingerprint_verified` | manifest; re-computed from the run's `config.yaml` copy (false if the copy was edited) |
| `dataset_hash`, `corpus_hash` | manifest `dataset.sha256`, `corpus.manifest_sha256` |
| `target_factory`, `embedding_config`, `retrieval_config`, `generator_config`, `judge_config`, `metrics` | manifest `config` |
| `judge_deferred`, `status`, `status_detail`, `other_runs` | manifest / benchmark |

Adding an experiment never changes the evaluator. The registry maps run names to ids, and graph-specific state is recorded through `target.record_keys`.

## 8. Langfuse

**Before this phase**
- Langfuse `run_experiment` already drove every run, in offline mode.
- With `langfuse.enabled: true`, runs used the Langfuse dataset and stored Ragas scores on each item's trace. That covered experiment → item → judge scores.

**Added (smallest integration)**
- `langfuse_sync.langchain_callbacks(enabled)` returns Langfuse's own `langfuse.langchain.CallbackHandler` when tracing is enabled. The runner passes it to the graph, so graph, retriever and LLM spans nest under each item's trace.
- When tracing is disabled it returns nothing: no import and no network.
- `make_client(True)` raises `LangfuseUnavailable` when the server is unreachable or the keys are wrong. The run therefore stops before any model call instead of running half-traced.
- No other tracing framework is used.

**Not traced:** the individual judge LLM calls. Ragas calls its OpenAI-compatible client directly (ADR 008), so only the resulting scores appear in Langfuse.

**Start a local server.** Reuse Langfuse's official self-hosting compose file; it is not vendored here.

```bash
git clone --depth 1 https://github.com/langfuse/langfuse.git ../langfuse
cd ../langfuse && docker compose up -d        # UI on http://localhost:3000
```

Then:
1. Create a project in the UI.
2. Put `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST=http://localhost:3000` in `.env`. `.env` is gitignored; never commit keys.
3. Run `python eval/runners/sync_langfuse_dataset.py`.
4. Set `langfuse.enabled: true` in a **new** experiment config. That changes the fingerprint, so it is a new run, and the baseline config stays as it is.

Offline tests cover tracing disabled, tracing enabled and an unreachable server without any Langfuse server.

## 9. Judge-capacity decision

**Measured**
- A full Ragas pass needs about 0.8–1M judge tokens per run.
- Groq's free tier gives 200k tokens per day per model, which is about 9 questions a day.
- So one run takes about 5 days, and 11 experiments take about 2 months.

**Options**

| Option | Throughput | Comparability with the baseline | Status |
|---|---|---|---|
| 1. Groq `qwen/qwen3.8-27b` (current judge) | ~9 items/day | Same judge: comparable | Keep as the **canonical** judge |
| 2. Local Ollama judge | No quota; speed depends on local hardware (not measured) | A different judge: scores are comparable only after re-judging the baseline answers into a new run | Not evaluated; needs its own design |
| 3. Other configured providers | Gemini free: 5 RPM; NVIDIA NIM: timeouts and 404s (Phase 2) | Different judge | Rejected in Phase 2 |
| 4. OpenRouter | Smoke test passed separately; free-model daily caps not measured | Different judge | Not integrated, per user decision |
| 5. Reduced, retrieval-only evaluation | Minutes per experiment, no judge | Fully comparable on retrieval | **Implemented**: ranking metrics + `--defer-judge` |
| 6. Separate retrieval and answer benchmarks | Answer judging only where needed | Same judge where judged | **Implemented** (two layers, section 6) |

**Recommendation: a two-tier gate. The judge is not changed.**

1. **Tier 1, every experiment, same day.** Run `python eval/runners/run_eval.py <config> --defer-judge`. This uses generator tokens only (about 55k for 42 items) and no judge tokens. Then run `benchmark.py --all`. Retrieval experiments (02 hybrid, 03 reranking, 04 query rewrite, 05 multi-query, 10 GraphRAG retrieval) must beat the baseline on paired ranking metrics to go further.
2. **Tier 2, judged.** Start a Ragas judgement through the daily `resume_eval.py` only for:
   - experiments that pass Tier 1, and
   - experiments whose change is on the generation side (06 CRAG, 07 Adaptive, 08 Self-RAG, 09 Agentic, 11 Multi-agent), which ranking metrics cannot assess.
3. **Changing the judge** (local or paid) is a separate decision for the user. It would need re-judging the baseline answers into a new run and an ADR, so it is not done here.

## 10. Cost model

- `eval/pricing.yaml` is a price book applied at report time. Each entry has provider, model, `input_price_per_million`, `output_price_per_million`, `currency`, `effective_date` and `source_url`.
- For each model in a run's token usage, the benchmark uses the latest entry in effect on the run's start date.
- If any model has no documented price, or currencies differ, the total is `null`.
- The book ships empty: no price was copied in this phase, so every cost is `null`. That is a valid result, not a gap to paper over.
- Covered: generator tokens only. Judge tokens are not captured (section 8).
- The run-time `pricing` list in each config is still honoured as before. The price book exists so that older runs can be costed without editing their configs.

## 11. Test strategy

- **Offline: 178 tests** (141 before this phase). They need no Langfuse, Qdrant, Groq, Gemini or network:

  | File | Covers |
  |---|---|
  | `test_ranking.py` | Recall@K, MRR and nDCG against hand-computed values; multiple relevant chunks; no relevant result; empty list; missing query; duplicates; old-run hash mapping; behaviour filter; paired subset |
  | `test_relevance.py` | docutils rendering; markup, spacing and footnote normalisation; cited-document restriction; unmatched-quote reporting; committed qrels match the current dataset |
  | `test_retrieval_trace.py` | rank; score present and missing; latency; method; a reranker wrapping a base retriever; `run_target` recording and failure |
  | `test_benchmark.py` | complete, partial, finalized, failed (unreadable / all errors), NOT RUN, duplicate and pinned runs, retrieval-only, missing metrics as `None`, paired exclusion, missing qrels, metadata contract incl. fingerprint verification, registry validation, cost null and priced |
  | `test_langfuse_tracing.py` | tracing disabled, enabled, server unavailable; runner passes the tracing callbacks to the graph |
  | `test_runner.py` (+2) | items record ranked retrieval results; `--defer-judge` leaves every item pending, then resume judges them |

- **Integration: 12 tests** (+3), needing Qdrant and Docling:
  - a fresh chunking reproduces the qrels catalog;
  - the baseline collection matches the catalog (read-only);
  - retrieval instrumentation works on the real Basic RAG graph.

## 12. Future experiment contract

To add experiment NN:

1. **Graph.** Write `archagenticrag.graphs.<name>:build_graph(system, *, client=None, embeddings=None, llm=None)`. It returns a compiled graph that takes `question` and returns `answer` and `documents` (`list[Document]` with `doc_id` and `chunk_id`), plus `eval_metadata`. Loops and conditional edges are allowed.
2. **Labelling.** Label each retriever with `with_config(metadata={"retrieval_method": "..."})`. Keep a score in document metadata when the component provides one; never invent one.
3. **Config.** Copy the baseline config and change only what the experiment changes. Add a test that the diff is exactly the documented one, as for the Phase 3.1 configs. New optional settings must stay out of the fingerprint while unset.
4. **New index.** If the experiment changes the index (chunking, sparse vectors, contextual chunks), use a new collection and run `eval/runners/build_qrels.py <config>` for it.
5. **Registry.** Add the run name to the experiment's entry in `eval/experiments.yaml`.
6. **Run.** Run `run_eval.py <config> --defer-judge`, then `benchmark.py --all` (Tier 1), then the daily `resume_eval.py <run_dir>` if Tier 2 applies.

## Appendix A: Reuse audit (2026-10-27)

| Need | Candidate | Package / version | License | Decision |
|---|---|---|---|---|
| Ranking metrics | ranx (named in the architecture audit) | `ranx` 0.3.21 | MIT | **Not adopted.** Pulls in 13 dependencies, including numba, pandas, seaborn, fastparquet and ir-datasets, for three metrics. |
| Ranking metrics | ir_measures on trec_eval | `ir-measures` 0.4.3 + `pytrec-eval-terrier` 0.5.11 | Apache-2.0 / MIT | **Adopted.** It is the reference trec_eval implementation. It adds two packages, since numpy and scipy were already installed, and there are cp312/cp313 Windows wheels. |
| Ranking metrics | `sklearn.metrics.ndcg_score` | not installed | BSD-3 | Not adopted: no MRR or Recall@K, and adds scikit-learn |
| Relevance labels | Ragas `NonLLMContextRecall` / string-similarity matching | `ragas` 0.4.3 (installed) | Apache-2.0 | Not adopted: these are fuzzy per-item scores, not reproducible labels. The deterministic docutils render plus token containment rule needs no new package. |
| Quote rendering | docutils (already the ingestion's RST renderer) | `docutils` 0.23 (installed) | Public domain (core) | **Reused** |
| Retrieval capture | LangChain retriever callbacks | `langchain-core` (installed) | MIT | **Reused**. There is no LangChain or Langfuse component that writes ranked results into our item records, so a 60-line handler was written as glue. |
| Tracing | Langfuse LangChain `CallbackHandler` | `langfuse` 4.16.0 (installed) | MIT | **Reused**. No second tracing framework. |
| Local tracing server | Official Langfuse docker compose | `langfuse/langfuse` repository | MIT (core) | **Referenced**, not vendored |
| Hybrid / rerank (future 02, 03) | `RetrievalMode.HYBRID`, `FastEmbedSparse("Qdrant/bm25")`, Qdrant `FusionQuery`, fastembed `TextCrossEncoder` | installed | MIT / Apache-2.0 | Not used in this phase. The instrumentation records their scores through metadata when the experiments use them. |
| Benchmark table / registry | — | — | — | Built as glue (about 300 lines). There is no tool that reads our run format; the registry is a YAML file validated with pydantic. |
