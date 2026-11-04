# Experiment 02: Hybrid Retrieval (dense + BM25, Qdrant RRF)

Status: retrieval-only evaluation complete; answer judging NOT RUN (run 2026-10-27, completed 2026-10-29). Decision: **WIN** (retrieval level; section 16).

## 1. Research question

Does hybrid retrieval (dense semantic search combined with sparse BM25 lexical search) retrieve the correct **evidence-bearing chunks** better than the Basic RAG baseline's dense retrieval?

A second, separate question is whether the final answers improve. That is a Ragas question and is not answered here (section 16).

## 2. Hypothesis

Phase 3.0 measured, on the baseline:
- document-level Recall@4 of 0.981;
- chunk-level Recall@4 of 0.587.

So retrieval usually finds the right PEP but not the chunk that holds the evidence. Phase 3.1 also showed the dense model (bge-small) ignoring exact identifiers such as "PEP 518".

BM25 scores exact tokens, including numbers, names and API identifiers. Fused with the dense ranking, it should rank evidence-bearing chunks higher, mainly for questions with exact identifiers or rare terms.

## 3. Reuse audit (fresh, 2026-10-27)

| Capability | Existing solution | Version | License | Decision |
|---|---|---|---|---|
| Dense retrieval | Project's `QdrantVectorStore` + FastEmbed `BAAI/bge-small-en-v1.5` | langchain-qdrant 1.1.0, fastembed 0.8.1 | MIT / Apache-2.0 (model MIT) | **REUSE**, unchanged |
| Sparse retrieval (BM25) | `langchain_qdrant.FastEmbedSparse("Qdrant/bm25")`, which wraps fastembed's `Bm25` | langchain-qdrant 1.1.0, fastembed 0.8.1, model `Qdrant/bm25` @ `22b8d2a` | MIT / Apache-2.0 / Apache-2.0 | **REUSE** |
| IDF for BM25 | Qdrant sparse vector `modifier=idf` (fastembed's `Bm25` docstring: "expected to be used with `modifier="idf"`") | Qdrant server 1.19.1, qdrant-client 1.19.1 | Apache-2.0 | **ADAPT**: langchain-qdrant's own collection builder does not set the modifier, so our `index_documents` creates the collection with it |
| Hybrid query and fusion | `QdrantVectorStore(retrieval_mode=RetrievalMode.HYBRID)`: two Qdrant `Prefetch` branches fused by `FusionQuery(Fusion.RRF)` in a single `query_points` call | langchain-qdrant 1.1.0, Qdrant 1.19.1 | MIT / Apache-2.0 | **REUSE** as shipped |
| Retriever / graph | Basic RAG graph and `as_retriever(search_type="similarity")` | project | MIT | **REUSE**: the same `basic_rag:build_graph` runs both arms |
| Ranking metrics, qrels, benchmark | Phase 3.0 (`ranking.py` on ir-measures/trec_eval, `relevance.py`, `benchmark.py`) | ir-measures 0.4.3 | Apache-2.0 | **REUSE**. Added: `--experiments` filter, per-item wins/ties/losses against the baseline, nDCG columns, doc-level categories |
| Evaluation | Phase 2 runner, `--defer-judge`, resume | project | MIT | **REUSE**. Added: `resume_eval.py --no-judge` to re-run failed system calls without judging |
| Tracing | Phase 3.0 Langfuse LangChain callback (disabled by default) | langfuse 4.16.0 | MIT | **REUSE**, no change |

**Not adopted**
- `rank_bm25` / BM25S: an in-process index next to Qdrant would be a second sparse engine, which this experiment rules out.
- LangChain `EnsembleRetriever`: weighted RRF run on the client side, while Qdrant already fuses on the server side.
- Splade models: a different, learned sparse model, i.e. a second variable.

No new dependency was added. The BM25 model is downloaded by fastembed on first use.

## 4. Baseline configuration (control: 01 Basic RAG)

| Setting | Value |
|---|---|
| Config / fingerprint | `eval/configs/baseline-basic-rag.yaml` / `63bf3b5f990cc9e5` (unchanged) |
| Run | `20261001T173531Z-baseline-basic-rag-63bf3b5f-6227d9` (read only, not re-run) |
| Retrieval | dense cosine similarity, `top_k: 4`, collection `peps_v1_bge_small_docling_480` |
| Graph | `archagenticrag.graphs.basic_rag:build_graph` |

## 5. Hybrid configuration (treatment: 02)

| Setting | Value |
|---|---|
| Config / fingerprint | `eval/configs/exp02-hybrid-bm25.yaml` / `690aff0c9e3997bd` |
| Run | `20261027T180058Z-exp02-hybrid-bm25-690aff0c-85de18` |
| Graph | the same `basic_rag:build_graph`; its retriever is labelled `hybrid(dense+bm25,rrf)` in traces |
| Retrieval | `mode: hybrid`, `sparse: {provider: local, model: Qdrant/bm25, modifier: idf}`, `fusion: rrf`, `top_k: 4`, `search_type: similarity` |
| Collection | `peps_v1_bge_small_docling_480_hybrid_bm25` |

**Top-k semantics, verified in langchain-qdrant 1.1.0 source and pinned by a test.**
- One `query_points` call runs two prefetch branches: dense (`using=""`, `limit=4`) and BM25 (`using="langchain-sparse"`, `limit=4`).
- Qdrant fuses them with RRF and returns the final `limit=4`.
- So hybrid sees at most 8 candidates (4 dense + 4 BM25) and **delivers 4 chunks, the same as the baseline**. The comparison is 4 chunks against 4 chunks.
- langchain-qdrant ties the branch limit to `k`. A deeper candidate pool would need code outside the library and is left out on purpose.

**Scores.** RRF fuses *ranks*, not raw scores, so dense cosine values and BM25 values are never compared with each other. Qdrant returns an RRF score per point, but the LangChain retriever drops it (as for the dense baseline). The trace therefore records `score: null`, and all metrics use the final fused rank order.

## 6. Variables held constant

Dataset (golden v1.0.0, same sha256), corpus and its manifest hash, chunking (Docling HybridChunker, 480 tokens, the same 455 chunks with the same ids and texts, verified by hash), embedding model and dense vector config, `top_k` (4 delivered), graph, generator (`groq / openai/gpt-oss-120b`, temperature 0), prompt, judge config and metrics list, triage thresholds and relevance labels.

The test `test_experiment_02_config_differs_from_baseline_only_in_retrieval_mode_and_collection` pins the config diff to exactly: `run_name`, `retrieval.mode`, `retrieval.sparse`, `retrieval.fusion` and `retrieval.qdrant.collection`.

## 7. Variables changed

Only retrieval:
- the BM25 sparse branch;
- RRF fusion of the two branches.

The collection name changes because the index gains a sparse vector. There is no reranking, query rewriting, multi-query, HyDE, decomposition, compression or parent-child retrieval.

## 8. Collection / index design

**A new collection was required.** Hybrid search needs a sparse vector per point. Adding it to the baseline collection would modify the frozen baseline index, so a separate collection was built: `peps_v1_bge_small_docling_480_hybrid_bm25`.
- **Naming:** `<baseline collection>_hybrid_<sparse model>`.
- **Ingestion:** the same pipeline (`python -m archagenticrag.rag.ingest eval/configs/exp02-hybrid-bm25.yaml`): docutils, Docling, the same chunk ids, dense vectors (unnamed, 384-d, cosine, as in the baseline) **plus** the `langchain-sparse` BM25 vector with `modifier: idf`.
- **Recorded in collection metadata:** `retrieval_mode: hybrid`, `sparse`, the embedding model, chunking, corpus manifest hash and per-document chunk counts.

**Safety guards (tested)**
- `index_documents` refuses to replace an existing collection indexed for a different retrieval mode. A hybrid config pointed at the baseline name fails instead of deleting the baseline.
- `open_store` refuses a mode mismatch.
- Collections indexed before this experiment count as dense.

**Baseline collection after ingestion:** 455 points, `indexed_at 2026-10-01T14:31:48`, config hash `6313436b33369189`. All three are identical to the values captured before ingestion. It has no sparse vectors and no `retrieval_mode` (integration test).

**Qrels:** `build_qrels.py` on the hybrid config gives a file with the same chunk catalog (`catalog_sha256` equal) and identical labels. An integration test checks that the hybrid collection, the baseline collection and the qrels catalog hold the same 455 chunk texts.

## 9. Retrieval instrumentation

Phase 3.0's recorder captured hybrid retrieval with no change:
- per item: query, latency, `method: hybrid(dense+bm25,rrf)`, doc_id, chunk_id, rank (1–4), `score: null`;
- per call: `retrieval_calls`, one per question.

The fused list is the ranked list scored by Recall/MRR/nDCG.

Langfuse: the same `CallbackHandler` path applies when `langfuse.enabled` is true. It is off in this config, so there is no network and no Langfuse initialisation. No new tracing code.

## 10. Evaluation methodology

1. **Run.** `run_eval.py eval/configs/exp02-hybrid-bm25.yaml --defer-judge`: 42 questions, the same generator. Judging was deferred, so **no judge tokens were used**.
2. **Retry.** 6 questions failed on Groq's 8,000 tokens-per-minute generator limit (B06, C03, C05, E01, E05, F06). My live regression test was running at the same time, which contributed. Then the generator's daily quota ran out. They were re-run with `resume_eval.py --no-judge`, which re-runs only failed system calls and scores nothing: B06 on 2026-10-27, the other 5 on 2026-10-29. The final run has **42/42 answered, 0 system errors**, and every item has `retrieval_results`. The same single provider (Groq `openai/gpt-oss-120b`) was used throughout; no provider fallback.
3. **Compare.** `benchmark.py --experiments 01 02 --k 4 8 --json ...` (the JSON holds every cutoff in K ∈ {1, 3, 4, 5, 8, 10}). Ranking metrics come from ir_measures (trec_eval) against the Phase 3.0 qrels. Comparisons are paired: questions with a system error in either run are excluded, and the excluded and compared questions are listed in section 11.
4. **Item set.** Means cover answerable items (category A, B, C, F, G with qrels). D (clarify) and E (abstain) are analysed separately (sections 12 and 14).

## 11. Full retrieval results

| Item | Value |
|---|---|
| Runs | `20261001T173531Z-baseline-basic-rag-63bf3b5f-6227d9` (01) vs `20261027T180058Z-exp02-hybrid-bm25-690aff0c-85de18` (02) |
| Compared items | all 31 answerable items with qrels: A01–A07, B01–B06, C01–C06, F01–F06, G01–G06 |
| Excluded items | none (no system error in either run) |
| W/T/L | per-item wins / ties / losses of 02 against 01 |

**Chunk level** (evidence-bearing chunks are the relevant ones)

| Metric | 01 Basic RAG | 02 Hybrid | Δ | W/T/L |
|---|---:|---:|---:|---|
| Recall@1 | 0.422 | 0.513 | +0.091 | 7/21/3 |
| Recall@3 | 0.589 | 0.648 | +0.059 | 4/27/0 |
| Recall@4 | 0.589 | **0.680** | **+0.091** | 5/26/0 |
| Recall@5 | 0.589 | 0.680 | +0.091 | 5/26/0 |
| Recall@8 | 0.589 | 0.680 | +0.091 | 5/26/0 |
| Recall@10 | 0.589 | 0.680 | +0.091 | 5/26/0 |
| MRR | 0.640 | **0.761** | **+0.121** | 9/19/3 |
| nDCG@1 | 0.548 | 0.677 | +0.129 | 7/21/3 |
| nDCG@3 | 0.565 | 0.652 | +0.087 | 10/17/4 |
| nDCG@4 | 0.563 | **0.664** | **+0.101** | 11/16/4 |
| nDCG@5 | 0.563 | 0.664 | +0.101 | 11/16/4 |
| nDCG@8 | 0.563 | 0.664 | +0.101 | 11/16/4 |
| nDCG@10 | 0.563 | 0.664 | +0.101 | 11/16/4 |

Both systems deliver exactly 4 chunks, so every metric at K ≥ 4 equals its value at K = 4.

**Document level** (`source_documents` are the relevant ones)

| Metric | 01 | 02 | Δ | W/T/L |
|---|---:|---:|---:|---|
| Recall@1 | 0.806 | 0.806 | +0.000 | 0/31/0 |
| Recall@3 | 0.952 | 0.952 | +0.000 | 1/29/1 |
| Recall@4 (=@5, @8, @10) | 0.952 | 0.952 | +0.000 | 1/29/1 |
| MRR | 0.984 | 0.984 | +0.000 | 0/31/0 |
| nDCG@1 | 0.968 | 0.968 | +0.000 | 0/31/0 |
| nDCG@3 | 0.948 | 0.951 | +0.003 | 2/28/1 |
| nDCG@4 (=@5, @8, @10) | 0.948 | 0.951 | +0.003 | 2/28/1 |

**Significance.** Two-sided sign tests on the per-item wins and losses (ties dropped) are not significant at 0.05 with this sample:
- Recall@4: 5–0, p = 0.062;
- MRR: 9–3, p = 0.146;
- nDCG@4: 11–4, p = 0.118.

The direction is consistent, but 31 questions cannot establish it statistically.

**Cost of the change**
- Retrieval latency p50: 21.8 ms (01) and 18.8 ms (02). One extra BM25 query embedding is negligible; the two runs were measured on different days.
- Generator tokens: 47,117 in / 10,193 out (02) vs 45,018 / 9,174 (01).
- LLM calls per question: still 1.

## 12. Category-level results

Chunk level, paired, answerable items:

| Category | n | Recall@4 01 → 02 | MRR 01 → 02 | nDCG@4 01 → 02 |
|---|---:|---|---|---|
| A Direct factual | 7 | 0.857 → **1.000** | 0.786 → 0.893 | 0.804 → 0.919 |
| B Multi-sentence | 6 | 0.944 → 0.944 | 0.806 → **1.000** | 0.838 → 0.948 |
| C Multi-document | 6 | 0.139 → **0.278** | 0.250 → **0.500** | 0.143 → 0.294 |
| F Retrieval challenge (lexical vs semantic) | 6 | 0.500 → 0.500 | 0.667 → **0.472** | 0.538 → **0.449** |
| G Multi-hop | 6 | 0.458 → **0.625** | 0.667 → **0.917** | 0.449 → 0.667 |

Document level, by category: A, B and F are unchanged; G Recall@4 rises from 0.917 to 1.000; C Recall@4 falls from 0.833 to 0.750 (C02 drops one of its two documents from the top 4).

**Per-item changes** (chunk Recall@4 / MRR; all other items unchanged)
- **Gains (exact identifiers):**
  - A03 "PEP 257 … quotes": 0 → 1 / 0 → 0.25
  - C03 "PEP 518 and PEP 621": 0 → 0.33 / 0 → 1. This is the item the dense model failed in Phase 3.1.
  - C05 "PEP 484 … PEP 526": 0 → 0.5 / 0 → 0.5
  - G02 "PEP 604's X | Y": 0 → 0.5 / 0 → 1
  - G05: 0.5 → 1.0
- **Rank gains:**
  - A04, B02, B03, C04, G01: MRR rises to 1.0
- **Losses (rank only; Recall@4 unchanged):**
  - F01 "What does `from __future__ import annotations` do?": MRR 1 → 0.33. The golden notes flag this exact import string as also appearing in PEP 585 and PEP 649 as distractors, and BM25 rewards those distractors.
  - F04, a semantic paraphrase that avoids "pyproject", "build-system" and "requires": MRR 1 → 0.5.
  - C02: MRR 1 → 0.5.

**D (ambiguous, 4 items with qrels, not in the headline)**
- D04: 0 → 0.5 / 0 → 0.5
- D05: 0.33 → 0.67 / 0.5 → 1.0
- D03 "What does the pyproject.toml PEP specify?": 0.5 → 0 / 0.33 → 0
- D01: unchanged at 0

**Category F verdict.** The hypothesis that BM25 helps "lexical" questions is **not** supported by category F: F's Recall@4 is unchanged and its MRR fell. The identifier gains came in A, C and G instead, i.e. questions that name a PEP number or a specific term. F's lexical items were built around distractor documents that share the exact string, which is exactly where lexical matching is weakest.

## 13. Baseline comparison

Output of `python eval/runners/benchmark.py --experiments 01 02 --k 4 8` (2026-10-29):

| Experiment | Status | Pass | Recall@4 | Recall@8 | MRR | nDCG@4 | nDCG@8 | Faithfulness | Correctness | Latency p50 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 01 Basic RAG | COMPLETE | 27/42 | 0.589 | 0.589 | 0.640 | 0.563 | 0.563 | 0.847 (n=34) | 0.724 (n=30) | 6.92 s |
| 02 Hybrid retrieval (dense + BM25, RRF) | IN PROGRESS | 0/0 judged (42 pending) | 0.680 | 0.680 | 0.761 | 0.664 | 0.664 | — | — | 9.13 s |

- 02 is `IN PROGRESS` only because its answers are not judged. Its retrieval evaluation is complete.
- The baseline row is unchanged (27/42, 0.847, 0.724, 6.92 s). Its ranking numbers here (paired over 31 items) differ from the Phase 3.0 snapshot (26 items), because no item is excluded in this two-run comparison.
- In `benchmark.py --all`, the NOT RUN experiments still show `—`.
  - That view pairs over every compared run, so items another run failed on (B02, C05, F02, F06, G02 from the 3.1 and control runs) drop out, leaving 26 items.
  - There 02 shows Recall@4 0.657 vs 0.587, and MRR 0.734 vs 0.673. Same direction, smaller sample.
- End-to-end latency also includes Groq queueing on different days; it is not a retrieval-cost measurement.

## 14. Interpretation

1. **The bottleneck moved as predicted.**
   - Document-level retrieval was already near its ceiling (Recall@4 0.952) and did not change.
   - Chunk-level retrieval improved: one more evidence-bearing chunk in the top 4 for 5 of 31 questions, and none lost.
   - So hybrid fixes *which chunk* of the right PEP is retrieved, the gap Phase 3.0 measured.
2. **Exact identifiers drive the gains.** PEP numbers ("PEP 518", "PEP 526", "PEP 604") and specific terms such as "docstrings" and "quotes" are the questions that gained most. bge-small embeddings blur them, and BM25 does not.
3. **Lexical matching has a known cost.**
   - It promotes chunks that share an exact string without answering, as with F01's distractors.
   - In D03 ("the pyproject.toml PEP"), the term appears throughout PEP 621. The top 4 filled with its sections and pushed out the two header chunks that hold the evidence.
   - It does not help paraphrases (F04).
   - With only 4 candidates per branch, RRF cannot recover from both branches disagreeing.
4. **Out-of-corpus questions (E01–E06).** Hybrid still returns 4 chunks, as dense does; it cannot return fewer.
   - The chunks differ from the baseline's: 2–3 of 4 are shared per item. They are ordinary sections of unrelated PEPs (e.g. E01, about PEP 703: sections of PEPs 563, 572, 544 and 649).
   - The context is not more relevant; it is a different set of irrelevant chunks.
   - All six hybrid answers decline ("The provided documents do not contain …"). That is the answer text, not a judged abstention score, which is not run.
   - No false sense of relevance appears in the metrics, because E items have no qrels and do not enter the means.
5. **Answer quality is unknown.** Better evidence retrieval makes a better answer likely for A, C and G questions, but this experiment does not measure it (section 16).

## 15. Limitations

- **Sample size.** n = 31 answerable items. No difference reaches p < 0.05 on a sign test; the result is directional.
- **Labels.** Binary evidence-quote labels (Phase 3.0). A paraphrasing chunk counts as not relevant.
- **Branch depth.** langchain-qdrant ties each branch's prefetch depth to `top_k` (4). A deeper candidate pool (e.g. 20 per branch) might fuse better but needs code outside the library; it is untested here.
- **Fusion.** RRF only, with Qdrant's default constant. DBSF and weighted fusion are untested.
- **Run conditions.** The 5 retried questions ran two days after the rest, with the same config, model and collection. Generator output is not deterministic, but the retrieval part is.
- **Latency.** Latency comparisons span different days and provider load.
- **Answers.** Answers were not judged; no Ragas metric exists for 02.

## 16. Decision

**WIN**, at retrieval level.

- **Gains:** Hybrid improves every headline evidence-retrieval metric (chunk Recall@4 +0.091, MRR +0.121, nDCG@4 +0.101). It loses no evidence chunk from any question's top 4 (Recall@4 5–0).
- **No broad regression:** document-level retrieval is unchanged and no category loses Recall@4.
- **Caveat 1, category F:** category F's ranking quality fell (MRR −0.195 over 6 items, driven by F01 and F04).
- **Caveat 2, significance:** the improvement is not statistically significant at n = 31.

**Answer evaluation: NOT RUN.** Answers for all 42 questions are recorded, and no judge tokens were spent. The retrieval gain is large enough to justify a judged comparison. That is the next step, through the daily `resume_eval.py eval/results/20261027T180058Z-exp02-hybrid-bm25-690aff0c-85de18`, with the canonical Groq judge and unchanged Ragas configuration. The run is the user's call, because it uses about 5 days of judge quota.

