# Phase 2: Basic RAG Baseline

> **Status: BLOCKED. No baseline has been measured.**
>
> The evaluation harness, golden dataset, configuration and tests are complete and verified. The baseline run itself could not be executed, for three reasons:
>
> 1. **The Phase 1 Basic RAG graph does not exist in this repository.** `archagenticrag.graphs.basic_rag:build_graph` cannot be imported. The repo contained only `docs/phase-0-research.md` when Phase 2 started.
> 2. **No model provider keys** (`GEMINI_API_KEY` etc.) are set in the environment.
> 3. **Docker Desktop is not running**, so the self-hosted Langfuse and Qdrant stacks are unavailable.
>
> Every section below that needs measurements says **NOT RUN**. No numbers here are estimated or invented. The run command at the end fills this log once the blockers are cleared.

## System Configuration

This is the configuration the baseline will be measured with, from [eval/configs/baseline-basic-rag.yaml](../../eval/configs/baseline-basic-rag.yaml):

| Setting | Value |
|---|---|
| Architecture | Question → Retrieve → Generate → Answer (no rewriting, grading, routing or reflection) |
| Generator | Gemini `gemini-3.8-flash`, temperature 0 (via the OpenAI-compatible endpoint) |
| Embeddings | Gemini `gemini-embedding-001` |
| Retrieval | dense similarity, top_k = 4 |
| Reranker | none |
| Chunking | recursive character, 1000 chars, 150 overlap |
| Judge (Ragas) | Gemini `gemini-3.8-flash`, Ragas default args (temperature 0.01, max_tokens 1024) |
| Judge embeddings | Gemini `gemini-embedding-001` |
| Eval framework | ragas 0.4.3, langfuse 4.16.0 (offline mode), langchain-core 1.6.6, langchain-community 0.3.31 |
| Dataset | peps-golden v1.0.0 (42 items) over corpus peps-v1 (python/peps @ `50803e5f`) |

The model names come from Google's OpenAI-compatibility docs on 2026-10-01. `run_eval.py` re-checks them against the provider's `/models` list before running.

The generator, embedding, retrieval and chunking values are **proposed defaults for Phase 1**. When the Phase 1 graph lands, the config must be changed to match what it actually uses (or the graph built from this config). The run manifest records the config verbatim either way.

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

**NOT RUN.** Per-category tables will be produced from `eval/results/<run_id>/summary.json` (`metrics_by_category`, `pass_rate_by_category`).

## Failure Analysis

**NOT RUN.** Every item gets a provisional label from `analysis.triage`. It blames the earliest failing pipeline stage:

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

Labels are a starting point. Each failed item will be read by hand (answer, contexts, metric reasons) before the analysis is written.

## Failure Matrix

**NOT RUN.**

| Failure Type | Count | % |
|---|---:|---:|
| Retrieval failure | — | — |
| Context insufficient | — | — |
| Generation failure | — | — |
| Hallucination | — | — |
| Ambiguous question | — | — |
| Out of corpus | — | — |
| Other | — | — |

## Cost

**NOT RUN.**
- Token counts for the system under test are captured per item, per model, through LangChain's `UsageMetadataCallbackHandler`.
- `pricing: []` in the config means cost is reported as `null` (unknown). A price is only added with its source URL and verification date.
- Ragas judge tokens are **not** captured. Judge cost must be read from the provider dashboard.

## Latency

**NOT RUN.** The run records end-to-end latency per item (mean, p50, p95), retriever time via LangChain callbacks, and LLM call count per item.

## Observations

None yet: no run.

## Limitations

- The baseline depends on a Phase 1 graph that is not present.
- Judge and generator are the same model family (self-preference risk).
- 42 items is enough to see category-level patterns, but too few for small deltas. Repeat runs are needed to estimate judge variance before comparing patterns.
- The ground truth was written by one author (the assistant) from verbatim corpus quotes. The quotes are machine-verified, but the wording of the reference answers has not been independently reviewed.
- The Langfuse server path is untested live.

## Next Experiments

These are for Phase 3 and later. They are listed only, not implemented.

1. Once the run has happened: repeat the baseline 3× to measure judge variance.
2. A cross-family judge (e.g. an OpenRouter or NVIDIA model) to check self-preference bias.
3. Hybrid (BM25 + dense) retrieval: is the gap between the lexical F items and the semantic F items real?
4. top_k sweep (4 / 8) to separate CONTEXT_FAILURE from generation issues.
5. Then the agentic patterns from the Phase 0 plan, each measured against this baseline.

## How to complete this log

```bash
# 1. Phase 1 graph available at archagenticrag.graphs.basic_rag:build_graph(system=...)
# 2. export GEMINI_API_KEY=...
.venv/Scripts/python eval/runners/run_eval.py eval/configs/baseline-basic-rag.yaml
# optional, with the self-hosted Langfuse stack running and LANGFUSE_* set:
.venv/Scripts/python eval/runners/sync_langfuse_dataset.py eval/configs/baseline-basic-rag.yaml
#   then set langfuse.enabled: true in the config and re-run
```
