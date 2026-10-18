# Phase 2: Basic RAG Baseline

> **Status: MEASURED (2026-10-15).** Run `20261001T173531Z-baseline-basic-rag-63bf3b5f-6227d9`: 42/42 answers, 169 of 175 metric values (6 judge-limit gaps, recorded). Full results: [PHASE-2-BASELINE-RESULTS.md](../PHASE-2-BASELINE-RESULTS.md).
>
> The sections below keep the original plan; the configuration table reflects what was actually run.

## System Configuration

This is the configuration the baseline will be measured with, from [eval/configs/baseline-basic-rag.yaml](../../eval/configs/baseline-basic-rag.yaml):

| Setting | Value |
|---|---|
| Architecture | Question → Retrieve → Generate → Answer (no rewriting, grading, routing or reflection) |
| Generator | Groq `openai/gpt-oss-120b`, temperature 0 |
| Embeddings | FastEmbed `BAAI/bge-small-en-v1.5` (local, 384-d) |
| Retrieval | Qdrant, dense cosine similarity, top_k = 4 |
| Reranker | none |
| Chunking | Docling HybridChunker, 480 bge tokens, 455 chunks |
| Judge (Ragas) | Groq `qwen/qwen3.8-27b`, temperature 0, Ragas default max_tokens 1024 |
| Judge embeddings | Gemini `gemini-embedding-001` |
| Eval framework | ragas 0.4.3, langfuse 4.16.0 (offline mode), langchain-community 0.3.31 |
| Dataset | peps-golden v1.0.0 (42 items) over corpus peps-v1 (python/peps @ `50803e5f`) |

The planned Gemini configuration was replaced. Gemini's free tier allows 5 requests/minute, and NVIDIA NIM timed out. ADR 008, Amendment 1 has the details.

## Dataset

- **Corpus.** 13 Python Enhancement Proposals: PEP 8, 20, 257, 484, 518, 526, 544, 563, 572, 585, 604, 621 and 649. That is 61,294 words in total.
  - **License:** every PEP is placed in the public domain, and the newer ones are also dual-licensed under CC0-1.0. This was checked per file.
  - **Provenance:** pinned to python/peps commit `50803e5f0aa404f34093c16d13a9bd7d21d904d1`, with a sha256 per file in `data/corpus/peps/MANIFEST.json`.
- **Golden set.** 42 items in `eval/datasets/peps-v1/golden.json`.
  - Every answerable and ambiguous item cites **verbatim evidence quotes**: 80 in total, 2.2 per answerable item.
  - A test checks every quote against the pinned corpus files, and checks the files against their hashes.
- **Why PEPs:**
  - They are redistributable and technical.
  - They are heavily cross-referenced (484 → 526 → 563 → 649; 484 → 585/604; 518 → 621), which makes genuine multi-document and multi-hop questions possible.
  - They contain both identifiers (good for lexical retrieval) and prose (good for semantic retrieval).

### Dataset statistics

| Category | Items | Expected behaviour | Difficulty |
|---|---:|---|---|
| A: Direct factual | 7 | answer | 7 easy |
| B: Multi-sentence evidence | 6 | answer | 6 medium |
| C: Multi-document evidence | 6 | answer | 5 medium, 1 hard |
| D: Ambiguous | 5 | clarify | 5 medium |
| E: Out-of-corpus | 6 | abstain | 3 easy, 3 medium |
| F: Retrieval challenge (lexical vs semantic) | 6 | answer | 4 medium, 2 hard |
| G: Multi-hop | 6 | answer | 6 hard |
| **Total** | **42** | 31 answer / 5 clarify / 6 abstain | 10 easy / 23 medium / 9 hard |

- 13 items need evidence from two or more documents.
- Two out-of-corpus items (E02 f-strings, E05 semicolons) are **distractors**: the corpus mentions the term in an unrelated context.
- F01, F02 and F05 are lexical (exact identifiers). F03, F04 and F06 are semantic paraphrases that avoid the documents' wording.

**Document coverage** (items citing each PEP): 008 ×7, 563 ×6, 649 ×6, 484 ×5, 518 ×5, 544 ×4, 621 ×4, 604 ×3, 257/526/572/585 ×2, 020 ×1.

## Metrics

| Metric | Library / class | Applied to | Measures |
|---|---|---|---|
| faithfulness | Ragas `Faithfulness` | answer, clarify | Share of the answer's claims supported by the retrieved contexts |
| answer_relevancy | Ragas `AnswerRelevancy` (needs embeddings) | answer | How directly the answer addresses the question |
| context_precision | Ragas `ContextPrecisionWithReference` | answer | Whether relevant chunks are ranked above irrelevant ones |
| context_recall | Ragas `ContextRecall` | answer, clarify (when evidence exists) | Share of reference claims attributable to the retrieved contexts |
| answer_correctness | Ragas `AnswerCorrectness(weights=[1, 0], beta=5)` (question-aware; replaced `FactualCorrectness`, see ADR 008 Amendment 1) | answer | Recall-weighted share of ground-truth claims covered by the answer |
| abstention | Ragas `DiscreteMetric` | abstain | Did the system decline instead of inventing an answer? |
| clarification | Ragas `DiscreteMetric` | clarify | Did the system ask, or cover several interpretations? |
| source_doc_recall | deterministic (golden `source_documents` vs retrieved doc ids) | answer, clarify | Was the right *document* retrieved? |
| evidence_in_context | deterministic (golden quotes vs retrieved text) | answer, clarify | Was the right *chunk* retrieved? |

## Results

Overall: faithfulness 0.847, answer relevancy 0.887, context precision 0.756, context recall 0.783, answer correctness 0.724, abstention 6/6, clarification 0/5, pass 27/42. Per-category tables are in [PHASE-2-BASELINE-RESULTS.md](../PHASE-2-BASELINE-RESULTS.md), section 4.


## Failure Analysis

Every item gets a provisional label from `analysis.triage`. It blames the earliest failing pipeline stage:

| Label | Rule (provisional thresholds in the config) | Question it answers |
|---|---|---|
| RETRIEVAL_FAILURE | none of the item's source documents retrieved | 1. Was the correct document retrieved? |
| CONTEXT_FAILURE | right doc, but `context_recall` < 0.5 (flag `retrieval_too_narrow`) | 2–3. Was the correct chunk retrieved? Was the context sufficient? |
| HALLUCINATION | context sufficient, but `faithfulness` < 0.7 | 5. Did the LLM hallucinate? |
| GENERATION_FAILURE | sufficient and faithful, but `answer_correctness` < 0.5 or `answer_relevancy` < 0.5 | 4. Did the LLM understand the context? |
| AMBIGUITY | ambiguous item answered as if it had one meaning | 6. Was the question ambiguous? |
| OUT_OF_CORPUS | out-of-corpus item answered instead of declined | |
| OTHER | system error, metric error, or missing metric values | |
| flag `retrieval_too_broad` | `context_precision` < 0.5 while recall ≥ 0.5 | 7. Was retrieval too broad? |
| flag `retrieval_too_narrow` | set together with CONTEXT_FAILURE | 8. Was retrieval too narrow? |

Labels are a starting point. All 15 failed items were read by hand; the verified causes (which differ from the label for several items) are in the results report, section 5.

## Failure Matrix

| Label | Count | % of failures |
|---|---:|---:|
| AMBIGUITY | 5 | 33% |
| GENERATION_FAILURE | 4 | 27% |
| HALLUCINATION | 4 | 27% |
| CONTEXT_FAILURE | 1 | 7% |
| OTHER (unscorable) | 1 | 7% |
| RETRIEVAL_FAILURE, OUT_OF_CORPUS | 0 | 0% |

By verified cause:

- **Retrieval missed a document or section: 5.** In every multi-document miss, all 4 chunks came from one PEP.
- **No clarification: 5.**
- **Judge-side: 4.**
- **Unscorable: 1.**


## Cost

The generator used 45,018 input and 9,174 output tokens; cost is `null` (no published price entered).
- Token counts for the system under test are captured per item, per model, through LangChain's `UsageMetadataCallbackHandler`.
- `pricing: []` in the config means cost is reported as `null` (unknown). A price is only added with its source URL and verification date.
- Ragas judge tokens are **not** captured. Judge cost must be read from the provider dashboard.

## Latency

| | Mean | p50 | p95 |
|---|---:|---:|---:|
| End to end | 7.27 s | 6.92 s | 20.14 s |
| Retrieval | 26 ms | 22 ms | 44 ms |

Latency includes free-tier queueing. There is 1 LLM call per question.


## Observations

1. Single-document questions (A, B) and out-of-corpus abstention (E, 6/6) are strong.
2. Multi-document questions (C) collapse onto one PEP: precision 0.42, recall 0.64.
3. Ambiguous questions are never clarified (0/5).
4. 4 of 15 failures are judge-side.
5. Free-tier judging took 8 sessions over 2 weeks. Groq also began rejecting Ragas' 1,024-token judge requests (an output-tokens-per-minute limit).


## Limitations

- 6 metric values are unscorable on the free-tier judge (C04, G02, G03).
- `evidence_in_context` under-reports, because the golden quotes are raw reStructuredText.
- 42 items is enough to see category-level patterns, but too few for small deltas. Repeat runs are needed to estimate judge variance before comparing patterns.
- The ground truth was written by one author (the assistant) from verbatim corpus quotes. The quotes are machine-verified, but the wording of the reference answers has not been independently reviewed.
- The Langfuse server path is untested live.

## Next Experiments

The chosen next step is **Phase 3.1, query decomposition**, measured against two controls: B1 (`top_k=8`) and B2 (MMR). See [PHASE-3.1-DESIGN.md](../PHASE-3.1-DESIGN.md).

Still open:

- Repeat the run to measure judge variance.
- Hybrid retrieval: F showed no lexical gap (recall 0.94), so this is low priority.


## How to reproduce

```bash
.venv/Scripts/python eval/runners/run_eval.py eval/configs/baseline-basic-rag.yaml
.venv/Scripts/python eval/runners/resume_eval.py eval/results/<run_id>   # repeat after quota resets
```
