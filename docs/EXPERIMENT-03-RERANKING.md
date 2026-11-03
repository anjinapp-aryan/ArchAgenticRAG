# Experiment 03: Hybrid Retrieval + Cross-Encoder Reranking

Status: retrieval-level evaluation complete, 2026-11-03. Answer judging NOT RUN. Design and reuse audit: [EXPERIMENT-03-RERANKING-AUDIT.md](EXPERIMENT-03-RERANKING-AUDIT.md).

**Decision: REGRESSION against Experiment 02.** Do not adopt this configuration; Experiment 02 stays the best retrieval so far. A retrieval result says nothing about answer quality in either direction.

## 1. Research question

Does cross-encoder reranking of a deeper candidate pool put evidence-bearing chunks into the final top 4 better than Basic RAG (01) and Hybrid Retrieval (02)?

## 2. Hypothesis

Experiment 02's remaining losses looked like ranking problems among plausible chunks, so a cross-encoder reranking 20 candidates down to 4 should lift final Recall@4, MRR and nDCG@4 above 02's. **The data do not support this.**

## 3. Configuration

| Item | Value |
|---|---|
| Config / fingerprint | `eval/configs/exp03-hybrid-rerank.yaml` / `532e86f37f018e05` |
| Run | `20261103T012127Z-exp03-hybrid-rerank-532e86f3-595026` |
| Graph | the same `basic_rag:build_graph`; reranking is composed in `make_retriever`, below the graph |
| Candidates | Experiment 02's collection, `candidate_k: 20`: each branch 20, Qdrant RRF to 20 |
| Reranker | FastEmbed `TextCrossEncoder`, `jinaai/jina-reranker-v1-tiny-en` (Apache-2.0, 8,192-token context), ONNX on CPU |
| Composition | `FastEmbedRerank` (`rag/rerank.py`, a `BaseDocumentCompressor`) inside LangChain's `ContextualCompressionRetriever` |
| Final | `top_k: 4`, the same as 01 and 02 |
| Generator, prompt, dataset, qrels, judge config | unchanged. A test pins the config diff against 02 to `run_name`, `system.reranker` and `retrieval.candidate_k`. |

**Model selection.** The audit pre-registered bge-reranker-base, with jina-reranker-v1-tiny-en as the fallback if bge's CPU rerank p50 exceeded 3 s, decided before any quality measurement.

| Model | p50 | p95 | max | Gate |
|---|---:|---:|---:|---|
| BAAI/bge-reranker-base | 3.13 s | 5.77 s | 7.00 s | failed |
| jinaai/jina-reranker-v1-tiny-en | 0.72 s | 0.93 s | 0.97 s | passed |

Timed on all 42 questions' 20-candidate pools, while judging ran in the background. The gate was missed narrowly and was applied as written. See section 7 for the bge diagnostic.

## 4. Execution

- 42 questions with `--defer-judge`, so **no judge tokens were used** by this experiment.
- 3 questions (B02, C02, F03) hit Groq's tokens-per-minute limit, and were re-run with `resume_eval.py --no-judge`.
- Final state: 42/42 answered, 0 system errors, single provider (Groq `openai/gpt-oss-120b`), no fallback.
- `FASTEMBED_CACHE_PATH` was set to a permanent folder before the download.

## 5. Results

From `benchmark.py --experiments 01 02 03 --k 4 8`, plus the JSON for the other cutoffs. Paired over all 31 answerable items; none excluded. W/T/L = per-item wins / ties / losses of 03.

**Chunk level**

| Metric | 01 Basic | 02 Hybrid | 03 Rerank | 03 vs 01 | W/T/L | 03 vs 02 | W/T/L |
|---|---:|---:|---:|---:|---|---:|---|
| Recall@1 | 0.422 | 0.513 | 0.465 | +0.043 | 5/23/3 | −0.048 | 1/27/3 |
| Recall@3 | 0.589 | 0.648 | 0.616 | +0.027 | 4/25/2 | −0.032 | 2/25/4 |
| Recall@4 (= @5, @8, @10) | 0.589 | 0.680 | **0.648** | +0.059 | 5/24/2 | **−0.032** | 2/25/4 |
| MRR | 0.640 | 0.761 | **0.691** | +0.051 | 6/22/3 | **−0.070** | 1/25/5 |
| nDCG@1 | 0.548 | 0.677 | 0.613 | +0.065 | 5/23/3 | −0.065 | 1/27/3 |
| nDCG@3 | 0.565 | 0.652 | 0.604 | +0.039 | 5/21/5 | −0.049 | 3/21/7 |
| nDCG@4 (= @5, @8, @10) | 0.563 | 0.664 | **0.615** | +0.052 | 6/20/5 | **−0.049** | 3/21/7 |

**Document level**

| Metric | 01 | 02 | 03 | 03 vs 02 | W/T/L |
|---|---:|---:|---:|---:|---|
| Recall@1 | 0.806 | 0.806 | 0.806 | 0.000 | 1/29/1 |
| Recall@3 | 0.952 | 0.952 | 0.887 | −0.065 | 0/27/4 |
| Recall@4 (= @5, @8, @10) | 0.952 | 0.952 | **0.887** | **−0.065** | 0/27/4 |
| MRR | 0.984 | 0.984 | 0.984 | 0.000 | 1/29/1 |
| nDCG@1 | 0.968 | 0.968 | 0.968 | 0.000 | 1/29/1 |
| nDCG@3 | 0.948 | 0.951 | 0.901 | −0.050 | 1/25/5 |
| nDCG@4 (= @5, @8, @10) | 0.948 | 0.951 | 0.901 | −0.050 | 1/25/5 |

**Significance.** Two-sided sign tests are not significant at 0.05:

| Comparison | Recall@4 | MRR | nDCG@4 |
|---|---|---|---|
| 03 vs 02 | 2–4, p = 0.688 | 1–5, p = 0.219 | 3–7, p = 0.344 |
| 03 vs 01 | 5–2, p = 0.453 | 6–3, p = 0.508 | 6–5, p = 1.000 |

**Run-to-run variance** (5 local repeats of 03's retrieval, no LLM; 10 repeats of 02 from the audit):

| Metric | 03 | 02 repeats | 02 recorded run |
|---|---:|---:|---:|
| Recall@4 | 0.648 (stable) | 0.648–0.680, mean 0.674 | 0.680 |
| MRR | 0.688–0.691 | 0.699–0.772, mean 0.748 | 0.761 |
| nDCG@4 | 0.614–0.615 | 0.630–0.669, mean 0.655 | 0.664 |

03's MRR and nDCG@4 are below 02's lowest repeat, and its Recall@4 equals 02's lowest. So tie noise does not explain the gap. The reranker's own ordering is almost perfectly repeatable.

## 6. Candidate retrieval vs reranking

| Stage | Chunk Recall | MRR | nDCG@4 |
|---|---:|---:|---:|
| Candidate pool (20) | **R@20 0.874**, R@10 0.788; doc R@20 1.000 | — | — |
| First 4 candidates, no reranker (03-D diagnostic) | R@4 0.664 | 0.737 | 0.650 |
| After the reranker | R@4 0.648 | 0.691 | 0.615 |
| **Reranker lift** (W/T/L) | **−0.016** (2/25/4) | **−0.046** (3/24/4) | **−0.035** (5/20/6) |

- **Candidate retrieval worked.** 30 of 31 questions have at least one relevant chunk in the pool, and every question's source document is present.
- **The reranker did not surface it.** It kept 74% of the reachable evidence (0.648 of 0.874). For 11 questions (C02, C03, C06, F01, F03, F04, F05, G02, G03, G04, G05), evidence was in the pool but missed the final 4.
- **Candidate failures, not reranker failures:** C01 has no evidence in the pool; C02, C04, C05, F03 and G06 have only part of it.
- **Depth alone also cost a little.** The first 4 of the deeper pool score below 02 (R@4 0.664 vs 0.680), as the audit's probe predicted.

## 7. Diagnostic: is it just the small model?

One local pass with bge-reranker-base over the same 31 questions, on retrieval only. It is **not** an official result and replaces nothing:

| Model | R@1 | R@4 | MRR | nDCG@4 | Doc R@4 |
|---|---:|---:|---:|---:|---:|
| jina-reranker-v1-tiny-en (official) | 0.465 | 0.648 | 0.691 | 0.615 | 0.887 |
| bge-reranker-base (diagnostic) | 0.376 | 0.651 | 0.624 | 0.573 | 0.903 |
| 02 Hybrid, no reranker | 0.513 | 0.680 | 0.761 | 0.664 | 0.952 |

bge's Recall@4 is about equal, and its ranking metrics are lower. The regression is therefore not an artefact of choosing the smaller model.

## 8. Category results (chunk level, 01 → 02 → 03)

| Category | n | Recall@4 | MRR | nDCG@4 |
|---|---:|---|---|---|
| A Direct factual | 7 | 0.857 → 1.000 → 1.000 | 0.786 → 0.893 → 0.821 | 0.804 → 0.919 → 0.866 |
| B Multi-sentence | 6 | 0.944 → 0.944 → **1.000** | 0.806 → 1.000 → 1.000 | 0.838 → 0.948 → **0.987** |
| C Multi-document | 6 | 0.139 → 0.278 → 0.222 | 0.250 → 0.500 → 0.417 | 0.143 → 0.294 → 0.245 |
| F Retrieval challenge | 6 | 0.500 → 0.500 → 0.500 | 0.667 → 0.472 → 0.444 | 0.538 → 0.449 → 0.436 |
| G Multi-hop | 6 | 0.458 → 0.625 → **0.458** | 0.667 → 0.917 → **0.750** | 0.449 → 0.667 → **0.501** |

Document Recall@4 by category (01 → 02 → 03): C 0.833 → 0.750 → 0.667; G 0.917 → 1.000 → 0.750; A, B and F stay at 1.000.

**Changes from 02 (Recall@4; MRR):**
- **Gains:** B03 Recall@4 0.67 → 1.00; G01 Recall@4 0.50 → 1.00; C05 MRR 0.50 → 1.00.
- **Losses:** G02 Recall@4 0.50 → 0.00 and MRR 1.00 → 0.00; C02 Recall@4 0.33 → 0.00 and MRR 0.50 → 0.00; G04 and G05 Recall@4 1.00 → 0.50; A04 and C04 MRR 1.00 → 0.50; F04 MRR 0.50 → 0.33.
- **Original targets not fixed:** F01 and F04 stay at Recall@4 0.50, and F's MRR did not recover. D03 stays at 0.
- **D (not in the headline):** D05 Recall@4 0.67 → 0.33 and MRR 1.00 → 0.25; D04 MRR 0.50 → 0.33.

## 9. Interpretation

Measured:
1. Reranking helped questions with one information need (B) and hurt questions that need two documents or facts (C, G). Doc Recall@4 fell only in those two categories.
2. The reranker lost evidence that was already in the first 4 candidates as often as it found new evidence (2 wins, 4 losses on Recall@4).

Likely, but not tested here:
- A cross-encoder scores each chunk against the whole question separately, so several chunks about one sub-topic can outrank the single chunk that answers the other part. This fits finding 1, and it would suggest decomposition or diversity rather than a different reranker.

**Label caveat.** Relevance labels are binary and mark only chunks containing a gold quote. A reranker may prefer a chunk that answers without containing the quote, and that counts as a miss. So this result shows lost *gold evidence*, not necessarily worse answers. Only a judged comparison could show that.

## 10. Out-of-corpus questions

- All 6 hybrid-plus-rerank answers decline to answer. That comes from reading the answer text; abstention is not judged.
- The reranker still returns 4 chunks; this experiment adds no threshold or routing.
- Top reranker scores do not separate the two groups cleanly. E01–E06 score −0.846 to 1.865, while answerable questions have a median of 2.403 and a minimum of 1.644. E02 (1.696) and E05 (1.865) exceed that minimum.

## 11. Cost

| Item | Value |
|---|---|
| Candidate retrieval p50 | 27 ms |
| Whole retrieval step p50 | 1.2 s (1.15 s final-stage call, during the full run with concurrent calls) |
| End-to-end p50 | 9.26 s vs 9.13 s for 02 (different days and provider load) |
| Generator tokens | 46,513 in / 9,902 out; still 1 LLM call per question |
| Model download | 0.13 GB, plus 1.04 GB for bge (kept in the cache after the gate; removable) |

## 12. Limitations

- n = 31; no difference is statistically significant.
- Binary quote-based labels (section 9).
- Only `candidate_k` 20 and one official model tested; RRF only.
- Prefetch depth and reranking change together; section 6 separates them.
- Cross-encoder scores come from the ONNX models on CPU; the gate timing ran while judging was also running.
- Answers are recorded but not judged: **a retrieval regression is not an answer-quality regression**, just as a retrieval win is not an answer win.

## 13. Decision

**REGRESSION** against Experiment 02: chunk Recall@4 −0.032, MRR −0.070, nDCG@4 −0.049, document Recall@4 −0.065; the reranker's own lift is negative. Compared with Basic RAG it is still better on chunk metrics (+0.059, +0.051, +0.052) but worse on document Recall@4 (−0.065). Not statistically significant at n = 31; stable across repeats.

**Answer evaluation: NOT RUN.** Judging it is not recommended before Experiment 02's answers, which are the stronger candidate. Answers remain recorded in the run if a judged comparison is wanted later.
